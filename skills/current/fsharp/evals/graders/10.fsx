open System
open System.IO
open System.Diagnostics
open System.Xml.Linq

let require condition reason = if not condition then failwith reason
let clean (text: string) = text.Replace("\r", " ").Replace("\n", " ")
let run directory arguments =
    let info = ProcessStartInfo("dotnet")
    info.WorkingDirectory <- directory
    info.RedirectStandardOutput <- true
    info.RedirectStandardError <- true
    info.Environment["DOTNET_NOLOGO"] <- "1"
    info.Environment["FSHARP_EVAL_TRACE"] <- Path.Combine(directory, "rotations.log")
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
        let testText =
            Directory.GetFiles(temp, "*.fs", SearchOption.AllDirectories)
            |> Array.filter (fun file -> Path.GetFileName(file) <> "Transform.fs")
            |> Array.map File.ReadAllText
            |> String.concat "\n"
        require (testText.Contains("FsCheck")) "No FsCheck property test was added"
        require (not (testText.Contains("==>") || testText.Contains("Prop.filter"))) "Generate valid rotations rather than discarding invalid inputs"
        require (not (testText.Contains("List.skip") || testText.Contains("List.take"))) "Property duplicates the rotation implementation"
        let project = XDocument.Load(Path.Combine(temp, "Tests.fsproj"))
        let packages = project.Descendants() |> Seq.filter (fun item -> item.Name.LocalName = "PackageReference")
        let fscheck = packages |> Seq.filter (fun item -> let id = item.Attribute(XName.Get "Include") in not (isNull id) && id.Value.Equals("FsCheck", StringComparison.OrdinalIgnoreCase)) |> Seq.exactlyOne
        let versionAttribute = fscheck.Attribute(XName.Get "Version")
        let version =
            if not (isNull versionAttribute) then versionAttribute.Value
            else fscheck.Elements() |> Seq.find (fun item -> item.Name.LocalName = "Version") |> fun item -> item.Value
        require (Version.Parse(version.Trim()).Major = 3) "Keep a pinned FsCheck 3.x package"
        require (testText.Contains("Gen.") || testText.Contains("Arb.")) "Property must generate its input domain"
        let transformPath = Path.Combine(temp, "Transform.fs")
        let original = File.ReadAllText(transformPath)
        require (System.Text.RegularExpressions.Regex.Replace(original, @"\s+", "") = "moduleTransformletrotateLeftcountvalues=List.skipcountvalues@List.takecountvalues") "Keep the supplied transformation unchanged"
        let tracePath = Path.Combine(temp, "rotations.log")
        let instrument implementation =
            File.Delete(tracePath)
            let renamed = System.Text.RegularExpressions.Regex.Replace(implementation, @"let\s+rotateLeft\b", "let private originalRotateLeft")
            let wrapper = "\nlet rotateLeft count values =\n    let length = List.length values\n    match System.Environment.GetEnvironmentVariable(\"FSHARP_EVAL_TRACE\") with\n    | null -> failwith \"Missing coverage trace path\"\n    | path -> System.IO.File.AppendAllText(path, sprintf \"%d,%d,%s\\n\" length count (values |> List.map string |> String.concat \";\"))\n    originalRotateLeft count values\n"
            write temp "Transform.fs" (renamed + wrapper)
        instrument original
        succeed temp ["run"; "--project"; "Tests.fsproj"; "--verbosity"; "quiet"] "Correct implementation failed its property suite"
        require (File.Exists(tracePath)) "Property never called the transformation"
        let firstTrace = File.ReadAllText(tracePath)
        File.Delete(tracePath)
        succeed temp ["run"; "--project"; "Tests.fsproj"; "--verbosity"; "quiet"] "Repeat property run failed"
        require (File.Exists(tracePath) && File.ReadAllText(tracePath) = firstTrace) "Property must replay the same generated inputs on repeated runs"
        let calls = File.ReadAllLines(tracePath) |> Array.map (fun line -> let fields = line.Split(',') in int fields[0], int fields[1])
        require (calls.Length >= 100) "Property must exercise at least 100 generated inputs"
        require (calls |> Array.forall (fun (length, count) -> length > 0 && count >= 0 && count < length)) "Property called transformation with invalid inputs"
        require (calls |> Array.map fst |> Array.distinct |> Array.length >= 5) "Property did not cover different list sizes"
        require (calls |> Array.filter (fun (_, count) -> count > 0) |> Array.length >= 10) "Property barely exercised nonzero rotations"
        write temp "Examples.fs" "module Examples\nopen Expecto\nlet suite = testCase \"example\" (fun _ -> ())\n"
        for name, implementation in ["identity", "module Transform\nlet rotateLeft (_count: int) (values: int list) = values\n"; "wrong count", "module Transform\nlet rotateLeft count values =\n    let wrong = (count + 1) % List.length values\n    List.skip wrong values @ List.take wrong values\n"] do
            instrument implementation
            let code, output = run temp ["run"; "--project"; "Tests.fsproj"; "--verbosity"; "quiet"]
            require (code <> 0 && not (output.Contains("error FS") || output.Contains("Build FAILED"))) ("Property did not fail at runtime for " + name + " mutant: " + clean output)
            require (output.Contains("Falsifiable") || output.Contains("Falsified")) ("Mutation failure must come from FsCheck: " + clean output)
    with error ->
        eprintfn "%s" (clean error.Message)
        status <- 1
finally
    if Directory.Exists(temp) then Directory.Delete(temp, true)
exit status
