open System
open System.IO
open System.Diagnostics
open System.Net
open System.Net.Http
open System.Text.Json
open System.Text.RegularExpressions
open System.Xml.Linq

let require condition reason = if not condition then failwith reason
let read path = File.ReadAllText(path)
let clean (text: string) = text.Replace("\r", " ").Replace("\n", " ")
let run directory arguments =
    let info = ProcessStartInfo("dotnet")
    info.WorkingDirectory <- directory
    info.RedirectStandardOutput <- true
    info.RedirectStandardError <- true
    info.UseShellExecute <- false
    info.Environment["DOTNET_NOLOGO"] <- "1"
    info.Environment["DOTNET_CLI_TELEMETRY_OPTOUT"] <- "1"
    info.Environment["DOTNET_CLI_UI_LANGUAGE"] <- "en"
    for argument in arguments do info.ArgumentList.Add(argument)
    use child = Process.Start(info)
    let stdout = child.StandardOutput.ReadToEndAsync()
    let stderr = child.StandardError.ReadToEndAsync()
    if not (child.WaitForExit(180000)) then
        child.Kill(true)
        child.WaitForExit()
        failwith ("Command timed out: dotnet " + String.concat " " arguments)
    child.ExitCode, stdout.Result + stderr.Result
let succeed directory arguments reason =
    let code, output = run directory arguments
    require (code = 0) (reason + ": " + clean output)
    output
let rec copy source target =
    Directory.CreateDirectory(target) |> ignore
    for file in Directory.GetFiles(source) do File.Copy(file, Path.Combine(target, Path.GetFileName(file)), true)
    for directory in Directory.GetDirectories(source) do
        if not (List.contains (Path.GetFileName(directory)) ["bin"; "obj"; ".git"]) then
            copy directory (Path.Combine(target, Path.GetFileName(directory)))
let files directory pattern =
    Directory.GetFiles(directory, pattern, SearchOption.AllDirectories)
    |> Array.filter (fun path ->
        let parts = Path.GetRelativePath(directory, path).Split(Path.DirectorySeparatorChar)
        not (parts |> Array.exists (fun part -> part = "bin" || part = "obj" || part = ".git")))
let elements name (document: XDocument) = document.Descendants() |> Seq.filter (fun e -> e.Name.LocalName = name) |> Seq.toArray
let attr name (element: XElement) =
    let value = element.Attribute(XName.Get name)
    if isNull value then "" else value.Value
let packageId element =
    let includeId = attr "Include" element
    if includeId = "" then attr "Update" element else includeId
let packageVersion element =
    let attribute = attr "Version" element
    if attribute <> "" then attribute
    else element.Elements() |> Seq.tryFind (fun e -> e.Name.LocalName = "Version") |> Option.map (fun e -> e.Value) |> Option.defaultValue ""
let declarations directory =
    Array.append (files directory "*.fsproj") (Array.append (files directory "*.props") (files directory "*.targets"))
    |> Array.collect (fun path ->
        let document = XDocument.Load(path)
        Array.append (elements "PackageReference" document) (elements "PackageVersion" document))
let handler = new HttpClientHandler(AutomaticDecompression = DecompressionMethods.All)
let http = new HttpClient(handler, Timeout = TimeSpan.FromSeconds(60.))
let fetch (url: string) =
    let rec attempt remaining =
        try http.GetStringAsync(url).GetAwaiter().GetResult()
        with _ when remaining > 0 -> attempt (remaining - 1)
    attempt 2 |> JsonDocument.Parse
let cache = Collections.Generic.Dictionary<string, (string * bool) array>(StringComparer.OrdinalIgnoreCase)
let registeredVersions (id: string) =
    match cache.TryGetValue(id) with
    | true, versions -> versions
    | _ ->
        use index = fetch ("https://api.nuget.org/v3/registration5-gz-semver2/" + id.ToLowerInvariant() + "/index.json")
        let versions = ResizeArray<string * bool>()
        let collect (page: JsonElement) =
            for leaf in page.GetProperty("items").EnumerateArray() do
                let entry = leaf.GetProperty("catalogEntry")
                let mutable listed = Unchecked.defaultof<JsonElement>
                let isListed = entry.TryGetProperty("listed", &listed) && listed.ValueKind = JsonValueKind.True
                versions.Add(entry.GetProperty("version").GetString(), isListed)
        for page in index.RootElement.GetProperty("items").EnumerateArray() do
            let mutable inlineItems = Unchecked.defaultof<JsonElement>
            if page.TryGetProperty("items", &inlineItems) then collect page
            else
                use expanded = fetch (page.GetProperty("@id").GetString())
                collect expanded.RootElement
        let result = versions.ToArray()
        require (result.Length > 0) ("NuGet registration returned no versions for " + id)
        cache[id] <- result
        result
let normalized (version: string) =
    let segments = version.ToLowerInvariant().Split([|'-'; '+'|], 2)
    let numeric = Version.Parse(segments[0])
    let numbers = [numeric.Major; numeric.Minor; max 0 numeric.Build; max 0 numeric.Revision] |> List.map string |> String.concat "."
    numbers + (if segments.Length = 2 then "-" + segments[1] else "")
let listed id version = registeredVersions id |> Array.exists (fun (candidate, isListed) -> isListed && normalized candidate = normalized version)
let latest id =
    registeredVersions id
    |> Array.filter (fun (version, isListed) -> isListed && not (version.Contains('-')))
    |> Array.maxBy (fun (version, _) -> Version.Parse(version))
    |> fst
let checkListed directory =
    for item in declarations directory do
        let version = packageVersion item
        if version <> "" then
            let id = packageId item
            require (listed id version) ("Package version is unlisted or nonexistent: " + id + " " + version)
        require (attr "VersionOverride" item = "" && elements "VersionOverride" (XDocument(item)) |> Array.isEmpty) "PackageReference VersionOverride must not bypass package validation"
let resolvedMajor directory id minimum =
    let resolved =
        files directory "*.fsproj"
        |> Array.collect (fun project ->
            let assets = Path.Combine(Path.GetDirectoryName(project), "obj", "project.assets.json")
            if not (File.Exists assets) then [||]
            else
                use json = JsonDocument.Parse(read assets)
                json.RootElement.GetProperty("libraries").EnumerateObject()
                |> Seq.choose (fun item ->
                    let split = item.Name.Split('/')
                    if split[0].Equals(id, StringComparison.OrdinalIgnoreCase) then Some split[1] else None)
                |> Seq.toArray)
    require (resolved.Length > 0 && resolved |> Array.forall (fun version -> Version.Parse(version).Major >= minimum)) (id + " must resolve to major " + string minimum + " or newer")
let executedCount (output: string) =
    let matches = Regex.Matches(output, @"(?im)(?:total(?:\s+tests)?\s*:\s*|tests?\s+run\s*:\s*)(\d+)")
    matches |> Seq.cast<Match> |> Seq.map (fun item -> int item.Groups[1].Value) |> Seq.sum
let test directory minimum =
    let output = succeed directory ["test"] "Root dotnet test failed"
    require (executedCount output >= minimum) ("Root dotnet test did not execute at least " + string minimum + " tests: " + clean output)
    output
let library directory =
    let source = Path.Combine(directory, "Library", "Ledger.fs")
    let expected = "module Ledger\n\nlet total (entries: int list) = List.sum entries\nlet credit amount balance = balance + amount\n"
    require (read source |> fun text -> text.Replace("\r\n", "\n") = expected) "Keep the supplied Ledger library unchanged"
let mutation directory requiredNames =
    let path = Path.Combine(directory, "Library", "Ledger.fs")
    let original = read path
    try
        File.WriteAllText(path, "module Ledger\nlet total (entries: int list) = List.sum entries + 1\nlet credit amount balance = balance + amount + 2\n")
        let code, output = run directory ["test"]
        require (code <> 0 && not (output.Contains("error FS") || output.Contains("Build FAILED"))) ("Ledger mutant must fail at runtime: " + clean output)
        require (output.Contains("Falsifiable") || output.Contains("Falsified") || Regex.IsMatch(output, @"Failed after \d+ tests?\.\s+Parameters:")) ("Root dotnet test must execute and fail the FsCheck property for the Ledger mutant: " + clean output)
        for name in requiredNames do
            require (Regex.IsMatch(output, @"(?im)^\s*Failed\s+(?:[^\r\n]*\.)?" + Regex.Escape(name) + @"\s+[\[(]")) ("Ledger mutant did not fail retained test " + name + ": " + clean output)
    finally
        File.WriteAllText(path, original)
let sentinel directory (project: string) =
    let document = XDocument.Load(project)
    let compile = elements "Compile" document
    require (compile.Length > 0) "Test project has no explicit F# compile items"
    let name = "HiddenSentinel.fs"
    File.WriteAllText(Path.Combine(Path.GetDirectoryName(project), name), "module HiddenSentinel\nopen Expecto\n[<Tests>]\nlet sentinel = testCase \"hidden failing sentinel\" <| fun _ -> failtest \"intentional sentinel failure\"\n")
    compile[0].AddBeforeSelf(XElement(XName.Get "Compile", XAttribute(XName.Get "Include", name)))
    document.Save(project)
    let code, output = run directory ["test"]
    require (code <> 0) "Root dotnet test swallowed an injected failing Expecto sentinel"
    require (not (output.Contains("error FS") || output.Contains("Build FAILED"))) ("Sentinel failed compilation instead of executing: " + clean output)
    require (executedCount output >= 4 && output.Contains("hidden failing sentinel")) ("Injected failing sentinel did not execute alongside the suite: " + clean output)
let main grade =
    let temp = Path.Combine(Path.GetTempPath(), "fsharp-eval-" + Guid.NewGuid().ToString("N"))
    let mutable status = 0
    try
        try
            require (fsi.CommandLineArgs.Length = 2 && Directory.Exists(fsi.CommandLineArgs[1])) "Usage: dotnet fsi grader.fsx <solved-dir>"
            copy (Path.GetFullPath(fsi.CommandLineArgs[1])) temp
            grade temp
        with error ->
            eprintfn "%s" (clean error.Message)
            status <- 1
    finally
        http.Dispose()
        handler.Dispose()
        if Directory.Exists(temp) then Directory.Delete(temp, true)
    exit status

let grade directory =
    let propsPath = Path.Combine(directory, "Directory.Packages.props")
    let props = XDocument.Load(propsPath)
    require (elements "ManagePackageVersionsCentrally" props |> Array.exists (fun item -> item.Value.Trim().Equals("true", StringComparison.OrdinalIgnoreCase))) "Keep Central Package Management enabled"
    let versions = elements "PackageVersion" props
    for id in ["FSharp.Core"; "Expecto"; "Expecto.FsCheck"; "FsCheck"; "YoloDev.Expecto.TestSdk"] do
        require (versions |> Array.exists (fun item -> packageId item = id)) ("Keep the centrally managed package " + id)
    for item in versions do
        let id = packageId item
        let expected = latest id
        require (packageVersion item = expected) (id + " must use the latest listed stable version " + expected + ", found " + packageVersion item)
    for item in declarations directory |> Array.filter (fun item -> item.Name.LocalName = "PackageReference") do
        require (packageVersion item = "" && attr "VersionOverride" item = "") "Keep every PackageReference versionless under Central Package Management"
    checkListed directory
    library directory
    let checks = read (Path.Combine(directory, "Tests", "Checks.fs"))
    for name in ["empty total"; "credit"; "singleton total"] do
        require (checks.Contains("\"" + name + "\"")) ("Keep the existing test " + name)
    require (checks.Contains("testProperty")) "Keep the FsCheck property test"
    succeed directory ["build"] "Solution build failed" |> ignore
    resolvedMajor directory "FsCheck" 3
    test directory 3 |> ignore
    mutation directory ["empty total"; "credit"; "singleton total"]
    sentinel directory (Path.Combine(directory, "Tests", "Tests.fsproj"))

main grade
