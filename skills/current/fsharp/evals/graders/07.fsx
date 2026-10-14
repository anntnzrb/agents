open System
open System.IO
open System.Diagnostics

let require condition reason = if not condition then failwith reason
let clean (text: string) = text.Replace("\r", " ").Replace("\n", " ")
let run directory arguments =
    let info = ProcessStartInfo("dotnet")
    info.WorkingDirectory <- directory
    info.RedirectStandardOutput <- true
    info.RedirectStandardError <- true
    info.Environment["DOTNET_NOLOGO"] <- "1"
    info.Environment["DOTNET_CLI_TELEMETRY_OPTOUT"] <- "1"
    for argument in arguments do info.ArgumentList.Add(argument)
    use child = Process.Start(info)
    let stdout = child.StandardOutput.ReadToEndAsync()
    let stderr = child.StandardError.ReadToEndAsync()
    if not (child.WaitForExit(90000)) then
        child.Kill(true)
        failwith "Command exceeded 90 seconds"
    child.ExitCode, stdout.Result + stderr.Result
let succeed directory arguments reason =
    let code, output = run directory arguments
    require (code = 0) (reason + ": " + clean output)
let rec copy source target =
    Directory.CreateDirectory(target) |> ignore
    for file in Directory.GetFiles(source) do File.Copy(file, Path.Combine(target, Path.GetFileName(file)), true)
    for directory in Directory.GetDirectories(source) do
        if not (List.contains (Path.GetFileName(directory)) ["bin"; "obj"; ".git"]) then
            copy directory (Path.Combine(target, Path.GetFileName(directory)))
let write directory name (text: string) = File.WriteAllText(Path.Combine(directory, name), text)
let project files references language output =
    let items = files |> List.map (fun name -> "<Compile Include=\"" + name + "\" />") |> String.concat ""
    let refs = references |> List.map (fun name -> "<ProjectReference Include=\"" + name + "\" />") |> String.concat ""
    "<Project Sdk=\"Microsoft.NET.Sdk\"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>" + output + "</OutputType><Nullable>enable</Nullable><TreatWarningsAsErrors>true</TreatWarningsAsErrors><EnableDefaultCompileItems>false</EnableDefaultCompileItems><NuGetAudit>false</NuGetAudit></PropertyGroup><ItemGroup>" + items + refs + "</ItemGroup></Project>"
let source = fsi.CommandLineArgs |> Array.skip 1
let mutable status = 0
let temp = Path.Combine(Path.GetTempPath(), "fsharp-eval-" + Guid.NewGuid().ToString("N"))
try
    try
        require (source.Length = 1 && Directory.Exists(source[0])) "Expected one existing solved directory"
        copy (Path.GetFullPath(source[0])) temp
        let fsFiles = Array.append (Directory.GetFiles(temp, "*.fs", SearchOption.AllDirectories)) (Directory.GetFiles(temp, "*.fsi", SearchOption.AllDirectories))
        let csFiles = Directory.GetFiles(temp, "*.cs", SearchOption.AllDirectories)
        for file in Array.append fsFiles csFiles do
            let content = File.ReadAllText(file)
            require (not (content.Contains("#nowarn") || content.Contains("#pragma warning"))) "Warning suppression is forbidden"
        for file in Directory.GetFiles(temp, "*.*proj", SearchOption.AllDirectories) do
            let content = File.ReadAllText(file)
            require (content.Contains("<Nullable>enable</Nullable>")) "Nullable analysis must remain enabled"
            require (not (content.Contains("NoWarn") || content.Contains("WarningsNotAsErrors") || content.Contains("--nowarn") || content.Contains("--warn:0"))) "Warning suppression is forbidden"
        require (File.ReadAllText(Path.Combine(temp, "Boundary.fs")).Contains("JsonApi.Deserialize")) "Boundary must consume the C# nullable API"
        succeed temp ["build"; "Boundary.fsproj"; "--verbosity"; "quiet"; "-p:Nullable=enable"; "-p:TreatWarningsAsErrors=true"] "Nullable-enabled library build failed"
        write temp "Hidden.fsproj" (project ["Probe.fs"] ["Boundary.fsproj"] "F#" "Exe")
        write temp "Probe.fs" """
        module Probe
        open System
        open People
        let ensure b m = if not b then failwith m
        let error json expected =
            match Boundary.decode json with
            | Error actual -> ensure (actual = expected) ("Incorrect error: " + actual + "; expected " + expected)
            | Ok _ -> failwith ("Accepted invalid JSON: " + json)
        [<EntryPoint>]
        let main _ =
            try
                for json in ["{"; "null"; "[]"; "{\"Name\":42,\"Age\":2}"; "{\"Name\":\"Ada\",\"Age\":\"2\"}"] do error json "Invalid JSON"
                for json in ["{}"; "{\"Age\":20}"; "{\"Name\":null,\"Age\":20}"; "{\"Name\":\"  \",\"Age\":-1}"] do error json "Name required"
                for json in ["{\"Name\":\"Ada\"}"; "{\"Name\":\"Ada\",\"Age\":null}"] do error json "Age required"
                for age in [-1; 131; Int32.MaxValue] do error (sprintf "{\"Name\":\"Ada\",\"Age\":%d}" age) "Age out of range"
                for age in [0; 42; 130] do
                    match Boundary.decode (sprintf "{\"Name\":\"  Ada  \",\"Age\":%d}" age) with
                    | Ok person -> ensure (person.Name = "Ada" && person.Age = age) "Valid JSON was not normalized correctly"
                    | Error message -> failwith ("Rejected valid JSON: " + message)
                let ty = typeof<Person>
                ensure (ty.GetConstructors().Length = 0) "Person has a public constructor bypassing validation"
                ensure (ty.GetProperties() |> Array.forall (fun p -> match p.SetMethod with null -> true | setter -> not setter.IsPublic)) "Person has publicly mutable properties"
                0
            with e -> eprintfn "%s" e.Message; 1
        """
        succeed temp ["run"; "--project"; "Hidden.fsproj"; "--verbosity"; "quiet"] "Nullable boundary behavior failed"
        write temp "Forge.fsproj" (project ["Forge.fs"] ["Boundary.fsproj"] "F#" "Library")
        write temp "Forge.fs" "module Forge\nopen People\nlet forged : Person = { Name = \"\"; Age = -1 }\n"
        let code, _ = run temp ["build"; "Forge.fsproj"; "--verbosity"; "quiet"]
        require (code <> 0) "External record construction bypasses Person validation"
        let libraryPath = Path.Combine(temp, "Boundary.fsproj")
        let libraryProject = File.ReadAllText(libraryPath)
        File.WriteAllText(libraryPath, libraryProject.Replace("</Project>", "<ItemGroup><Compile Include=\"ForgeInside.fs\" /></ItemGroup></Project>"))
        for expression in ["Person(\"\", -1)"; "({ Name = \"\"; Age = -1 } : Person)"] do
            write temp "ForgeInside.fs" ("module ForgeInside\nopen People\nlet forged = " + expression + "\n")
            let code, output = run temp ["build"; "Boundary.fsproj"; "--verbosity"; "quiet"]
            require (code <> 0 && output.Contains("error FS")) "Another source file can bypass Person validation"

    with error ->
        eprintfn "%s" (clean error.Message)
        status <- 1
finally
    if Directory.Exists(temp) then Directory.Delete(temp, true)
exit status
