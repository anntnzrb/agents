open System
open System.IO
open System.Diagnostics
open System.Text.RegularExpressions
open System.Xml.Linq
open System.Text.Json

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
    info.Environment.["DOTNET_CLI_UI_LANGUAGE"] <- "en"
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
let originalChecks = "module ArithmeticChecks\n\nopen Expecto\n\nlet tests =\n    testList \"arithmetic\" [\n        testCase \"addition\" <| fun _ -> Expect.equal (2 + 3) 5 \"addition\"\n        testCase \"multiplication\" <| fun _ -> Expect.equal (4 * 3) 12 \"multiplication\"\n        testCase \"negative\" <| fun _ -> Expect.equal (-2 + 1) -1 \"negative\"\n    ]\n"
let usesMtp dir =
    let path = Path.Combine(dir, "global.json")
    if not (File.Exists path) then false
    else
        use json = JsonDocument.Parse(File.ReadAllText path, JsonDocumentOptions(CommentHandling = JsonCommentHandling.Skip, AllowTrailingCommas = true))
        let mutable test = Unchecked.defaultof<JsonElement>
        let mutable runner = Unchecked.defaultof<JsonElement>
        json.RootElement.TryGetProperty("test", &test) && test.TryGetProperty("runner", &runner) && runner.GetString() = "Microsoft.Testing.Platform"
let testResults dir name mtp (output: string) =
    if mtp then
        let count label =
            let matches = Regex.Matches(output, @"(?m)^\s*" + label + @":\s*(\d+)\s*$")
            require (matches.Count = 1) ("MTP did not report a unique " + label + " count")
            int matches[0].Groups[1].Value
        let results =
            Regex.Matches(output, @"(?im)^\s*(passed|failed)\s+(.+?)\s+\([^\r\n]*\)\s*$")
            |> Seq.cast<Match>
            |> Seq.map (fun item -> item.Groups[2].Value, item.Groups[1].Value.ToLowerInvariant())
            |> Seq.toArray
        count "total", count "succeeded", count "failed", results
    else
        let resultPath = Path.Combine(dir, "grade-results", name)
        require (File.Exists resultPath) "dotnet test did not write a test results file"
        let doc = XDocument.Load resultPath
        let byName name = doc.Descendants() |> Seq.filter (fun e -> e.Name.LocalName = name)
        let counters = byName "Counters" |> Seq.exactlyOne
        let results = byName "UnitTestResult" |> Seq.map (fun item -> attr "testName" item, (attr "outcome" item).ToLowerInvariant()) |> Seq.toArray
        int (attr "executed" counters), int (attr "passed" counters), int (attr "failed" counters), results
let grade dir =
    let source = read dir "Checks.fs"
    let compact text = Regex.Replace(text, @"\s+", "")
    require ((source.Replace("[<Tests>]", "") |> compact).Contains(compact originalChecks)) "The existing test cases and assertions must remain unchanged"
    let project = loadXml dir "Checks.fsproj"
    require (elements "PackageReference" project |> Array.exists (fun e -> attr "Include" e = "Expecto")) "Expecto must remain the test framework"
    let mtp = usesMtp dir
    let test name =
        if mtp then run dir ["test"; "--project"; "Checks.fsproj"; "--output"; "Detailed"]
        else run dir ["test"; "Checks.fsproj"; "--nologo"; "-v:q"; "-p:NuGetAudit=false"; "--logger"; "trx;LogFileName=" + name; "--results-directory"; Path.Combine(dir, "grade-results")]
    let code, output = test "original.trx"
    require (code = 0) ("Existing dotnet test failed: " + detail output)
    let executed, passed, _, results = testResults dir "original.trx" mtp output
    require (executed = 3 && passed = 3 && results.Length = 3) "dotnet test must execute and pass exactly the three existing tests; zero discovery is not success"
    for name in ["addition"; "multiplication"; "negative"] do
        require (results |> Array.exists (fun (testName, outcome) -> testName.Contains name && outcome = "passed")) ("Existing test did not execute: " + name)
    write dir "Checks.fs" (source + "\n[<Tests>]\nlet hiddenSentinel = testCase \"hidden sentinel\" <| fun _ -> failtest \"intentional sentinel failure\"\n")
    let sentinelCode, sentinelOutput = test "sentinel.trx"
    require (sentinelCode <> 0) "dotnet test swallowed an injected failing Expecto test"
    let sentinelExecuted, _, sentinelFailed, sentinelResults = testResults dir "sentinel.trx" mtp sentinelOutput
    require (sentinelExecuted = 4 && sentinelFailed = 1 && sentinelResults |> Array.exists (fun (testName, outcome) -> testName.Contains("hidden sentinel") && outcome = "failed")) "The injected failing sentinel must execute alongside the original three tests"

main grade
