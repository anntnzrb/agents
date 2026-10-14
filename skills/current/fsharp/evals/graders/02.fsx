open System
open System.IO
open System.Diagnostics
open System.Text.RegularExpressions
open System.Xml.Linq

let require condition reason = if not condition then failwith reason
let read (dir: string) (name: string) = File.ReadAllText(Path.Combine(dir, name)).Replace("\r\n", "\n")
let write (dir: string) (name: string) (content: string) = File.WriteAllText(Path.Combine(dir, name), content)
let run (dir: string) (args: string list) =
    let info = ProcessStartInfo("dotnet")
    info.WorkingDirectory <- dir
    info.RedirectStandardOutput <- true
    info.RedirectStandardError <- true
    info.UseShellExecute <- false
    info.Environment.["DOTNET_NOLOGO"] <- "1"
    info.Environment.["DOTNET_CLI_TELEMETRY_OPTOUT"] <- "1"
    for arg in args do info.ArgumentList.Add arg
    use proc = Process.Start info
    let stdout = proc.StandardOutput.ReadToEndAsync()
    let stderr = proc.StandardError.ReadToEndAsync()
    if not (proc.WaitForExit(60000)) then
        proc.Kill(true)
        proc.WaitForExit()
        failwith ("Command timed out: dotnet " + String.concat " " args)
    proc.ExitCode, stdout.Result + stderr.Result
let detail (output: string) =
    output.Split('\n')
    |> Array.tryFind (fun line -> line.Contains("error ") || line.Contains("Exception:") || line.Contains("error:"))
    |> Option.defaultValue "see command output by running the project directly"
    |> fun line -> line.Trim()
let build dir project configuration =
    let code, output = run dir ["build"; project; "-c"; configuration; "--nologo"; "-v:q"; "-p:NuGetAudit=false"]
    require (code = 0) ("Project build failed: " + detail output)
let runFsi dir script content =
    write dir script content
    run dir ["fsi"; "--exec"; script]
let checkFsi dir script content reason =
    let code, output = runFsi dir script content
    require (code = 0) (reason + ": " + detail output)
let rec copyTree source target =
    Directory.CreateDirectory(target) |> ignore
    for file in Directory.GetFiles(source) do File.Copy(file, Path.Combine(target, Path.GetFileName(file)), true)
    for child in Directory.GetDirectories(source) do
        if not (Set.contains (Path.GetFileName(child)) (set ["bin"; "obj"; ".git"])) then
            copyTree child (Path.Combine(target, Path.GetFileName(child)))
let xname value = XName.Get value
let loadXml dir name = XDocument.Load(Path.Combine(dir, name))
let attr name (element: XElement) =
    let value = element.Attribute(xname name)
    if isNull value then "" else value.Value
let elements name (document: XDocument) = document.Descendants(xname name) |> Seq.toArray
let main grade =
    let temp = Path.Combine(Path.GetTempPath(), "fsharp-eval-" + Guid.NewGuid().ToString("N"))
    let mutable code = 0
    try
        try
            require (fsi.CommandLineArgs.Length = 2) "Usage: dotnet fsi grader.fsx <solved-dir>"
            let source = Path.GetFullPath(fsi.CommandLineArgs.[1])
            require (Directory.Exists source) "Solved directory does not exist"
            copyTree source temp
            grade temp
        with ex ->
            eprintfn "%s" (ex.Message.Replace("\r", " ").Replace("\n", " "))
            code <- 1
    finally
        if Directory.Exists temp then Directory.Delete(temp, true)
    exit code
let grade dir =
    require (XNode.DeepEquals(XDocument.Parse(read dir "Directory.Packages.props"), XDocument.Parse("<Project>\n  <PropertyGroup>\n    <ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally>\n  </PropertyGroup>\n  <ItemGroup>\n    <PackageVersion Include=\"FSharp.Core\" Version=\"10.1.401\" />\n  </ItemGroup>\n</Project>\n"))) "Central package policy and versions changed"
    let project = loadXml dir "Contacts.fsproj"
    let compile = elements "Compile" project |> Array.map (attr "Include")
    let index name = compile |> Array.tryFindIndex ((=) name) |> Option.defaultValue -1
    require (compile |> Array.forall (fun name -> not (name.Contains("*") || name.Contains("?")))) "Compile items must remain explicit"
    let signatures = compile |> Array.filter (fun name -> name.EndsWith(".fsi") && File.Exists(Path.Combine(dir, name)) && Regex.IsMatch(read dir name, @"(?m)^\s*type\s+Email(?:\s*$|\s*=\s*private\b)"))
    require (signatures.Length = 1) "Compile an .fsi signature exposing an opaque Email type"
    let signatureName = signatures.[0]
    let implementationName = Path.ChangeExtension(signatureName, ".fs")
    require (index implementationName > index signatureName && index implementationName < index "Report.fs") "Compile the Email signature before its implementation and consumer"
    let conditional = elements "ItemGroup" project |> Array.filter (fun group -> attr "Condition" group <> "")
    require (conditional.Length = 1 && attr "Condition" conditional.[0] = "'$(Configuration)' == 'Debug'" && conditional.[0].Elements(xname "Compile") |> Seq.map (attr "Include") |> Seq.toList = ["Diagnostics.fs"]) "The conditional Diagnostics compile group changed"
    require (elements "PackageReference" project |> Array.forall (fun reference -> attr "Version" reference = "" && attr "VersionOverride" reference = "" && not (reference.Elements() |> Seq.exists (fun e -> e.Name.LocalName = "Version" || e.Name.LocalName = "VersionOverride")))) "PackageReference must use central versions"
    build dir "Contacts.fsproj" "Debug"
    build dir "Contacts.fsproj" "Release"
    checkFsi dir "hidden-validation.fsx" "#r \"bin/Release/net10.0/Contacts.dll\"\nopen ContactValidation\nlet require condition reason = if not condition then failwith reason\nfor raw, expected in [\"alice@example.org\", \"alice@example.org\"; \"  x@y  \", \"x@y\"; \"User+tag@host\", \"User+tag@host\"] do\n    match Email.create raw with\n    | Ok email ->\n        require (Email.value email = expected) \"Email normalization changed\"\n        require (Report.render raw = \"Contact: \" + expected) \"Consumer must use validated normalized value\"\n    | Error _ -> failwith \"Valid address rejected\"\nfor raw in [null; \"\"; \" \"; \"a\"; \"@b\"; \"a@\"; \"a@@b\"; \"a b@c\"; \"a@b c\"; \"a\\t@b\"; \"a@b\\nc\"] do\n    require (Email.create raw |> Result.isError) \"Malformed address accepted\"\n    require (Report.render raw = \"Invalid contact\") \"Consumer accepted invalid address\"\n" "Hidden email behavior checks failed"
    let signature = read dir signatureName
    require (Regex.IsMatch(signature, @"(?m)^\s*type\s+Email(?:\s*$|\s*=\s*private\b)")) "The signature must expose an opaque Email type"
    let code, _ = runFsi dir "hidden-constructor.fsx" "#r \"bin/Release/net10.0/Contacts.dll\"\nopen ContactValidation\nlet forged = Email.Email \"not an address\"\n"
    require (code <> 0) "The raw Email constructor is public"

main grade
