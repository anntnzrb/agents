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
    build dir "Billing.fsproj" "Debug"
    checkFsi dir "hidden-rounding.fsx" "#r \"bin/Debug/net10.0/Billing.dll\"\nopen Billing\nfor subtotal, tax, expected in [1.005M, 0M, 1.01M; -1.005M, 0M, -1.01M; 2.345M, 0M, 2.35M; -2.345M, 0M, -2.35M; 10M, 0.1005M, 11.01M; 0M, 0.2M, 0M; 4.321M, 0M, 4.32M; 4.329M, 0M, 4.33M] do\n    if Invoice.total subtotal tax <> expected then failwithf \"Incorrect invoice rounding for %M at %M\" subtotal tax\n" "Hidden library rounding checks failed"
    require (File.Exists(Path.Combine(dir, "probe.fsx"))) "Leave an executable probe.fsx for the current library"
    let probes = Directory.GetFiles(dir, "*.fsx", SearchOption.AllDirectories) |> Array.filter (fun p -> Path.GetFileName(p).Contains("probe", StringComparison.OrdinalIgnoreCase))
    for probe in probes do
        let code, output = run dir ["fsi"; "--exec"; probe]
        require (code = 0) ("FSI probe failed: " + Path.GetFileName(probe) + ": " + detail output)
    write dir "Invoice.fs" "namespace Billing\n\nmodule Invoice =\n    let total (subtotal: decimal) (taxRate: decimal) : decimal = failwith \"hidden current-library marker\"\n"
    build dir "Billing.fsproj" "Debug"
    for probe in probes do
        let code, output = run dir ["fsi"; "--exec"; probe]
        require (code <> 0 && output.Contains("hidden current-library marker")) ("Probe does not exercise current library sources/build: " + Path.GetFileName(probe))

main grade
