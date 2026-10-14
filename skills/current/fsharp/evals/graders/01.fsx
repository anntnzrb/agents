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
    require (XNode.DeepEquals(XDocument.Parse(read dir "Directory.Build.props"), XDocument.Parse("<Project>\n  <PropertyGroup>\n    <LangVersion>8.0</LangVersion>\n    <DisableImplicitFSharpCoreReference>true</DisableImplicitFSharpCoreReference>\n  </PropertyGroup>\n</Project>\n"))) "The original LangVersion and FSharp.Core reference policy must be preserved"
    require (XNode.DeepEquals(XDocument.Parse(read dir "Reader.fsproj"), XDocument.Parse("<Project Sdk=\"Microsoft.NET.Sdk\">\n  <PropertyGroup>\n    <TargetFramework>net8.0</TargetFramework>\n    <GenerateDocumentationFile>true</GenerateDocumentationFile>\n  </PropertyGroup>\n  <ItemGroup>\n    <Compile Include=\"Reader.fs\" />\n  </ItemGroup>\n  <ItemGroup>\n    <PackageReference Include=\"FSharp.Core\" Version=\"8.0.403\" />\n  </ItemGroup>\n</Project>\n"))) "The net8.0 project and FSharp.Core 8.0.403 pin must be preserved"
    build dir "Reader.fsproj" "Debug"
    checkFsi dir "hidden-concurrency.fsx" "#r \"bin/Debug/net8.0/Reader.dll\"\nopen System\nopen System.Threading\nopen System.Threading.Tasks\nopen PinnedReads\n\nlet require condition reason = if not condition then failwith reason\nlet mutable calls = 0\nlet started = TaskCompletionSource<unit>(TaskCreationOptions.RunContinuationsAsynchronously)\nlet read value () = async {\n    if Interlocked.Increment(&calls) = 2 then started.TrySetResult(()) |> ignore\n    do! started.Task.WaitAsync(TimeSpan.FromSeconds 2.0) |> Async.AwaitTask\n    do! Async.Sleep 100\n    return value\n}\nlet result = Reader.readBoth (read \"left\") (read \"right\") |> fun work -> Async.RunSynchronously(work, 5000)\nrequire (result = (\"left\", \"right\")) \"Read results must retain argument order\"\nrequire (calls = 2) \"Each read must execute exactly once\"\nlet failing () : Async<string> = async { return failwith \"read exploded\" }\nlet ok () = async { return \"ok\" }\nfor work in [Reader.readBoth failing ok; Reader.readBoth ok failing] do\n    let mutable propagated = false\n    try Async.RunSynchronously(work, 5000) |> ignore\n    with ex -> propagated <- ex.Message.Contains(\"read exploded\")\n    require propagated \"Read exceptions must propagate\"\n" "Concurrent read or error-propagation check failed"

main grade
