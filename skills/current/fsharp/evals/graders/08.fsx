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
        require (File.ReadAllText(Path.Combine(temp, "Domain.fs")).Contains("Retry")) "Retry DU case is missing"
        write temp "Hidden.fsproj" (project ["Probe.fs"] ["Dispatch.fsproj"] "F#" "Exe")
        write temp "Probe.fs" """
        module Probe
        open Jobs
        let ensure b m = if not b then failwith m
        [<EntryPoint>]
        let main _ =
            try
                let mutable calls = []
                let fetch key = calls <- key :: calls; "data:" + key
                for job, expected in [Cached 9, "9"; Cached -1, "ignored"; Ignored, "ignored"; Retry("unused", 0), "ignored"; Retry("unused", -8), "ignored"] do
                    ensure (Dispatch.run fetch job = expected) "Existing or nonpositive Retry behavior changed"
                    ensure calls.IsEmpty "Fetch ran eagerly for a non-fetch case"
                ensure (Dispatch.run fetch (Remote "remote") = "data:remote") "Remote behavior changed"
                ensure (calls = ["remote"]) "Remote must fetch exactly once"
                for attempt in [1; 2; 19] do
                    calls <- []
                    ensure (Dispatch.run fetch (Retry("retry", attempt)) = sprintf "data:retry#%d" attempt) "Retry behavior is incorrect"
                    ensure (calls = ["retry"]) "Positive Retry must fetch exactly once"
                0
            with e -> eprintfn "%s" e.Message; 1
        """
        succeed temp ["run"; "--project"; "Hidden.fsproj"; "--verbosity"; "quiet"] "DU extension behavior failed"
        let domain = Path.Combine(temp, "Domain.fs")
        let text = File.ReadAllText(domain)
        require (text.Contains("| Ignored")) "Keep the existing Ignored case in Domain.fs"
        File.WriteAllText(domain, text.Replace("| Ignored", "| HiddenFutureCase\n    | Ignored"))
        let code, output = run temp ["build"; "Dispatch.fsproj"; "--verbosity"; "quiet"; "-p:WarningsAsErrors=FS0025"]
        require (code <> 0 && output.Contains("FS0025")) "Future DU case must cause FS0025; remove catch-all dispatch branches"
    with error ->
        eprintfn "%s" (clean error.Message)
        status <- 1
finally
    if Directory.Exists(temp) then Directory.Delete(temp, true)
exit status
