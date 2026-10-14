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
        write temp "Hidden.fsproj" (project ["Probe.fs"] ["Ownership.fsproj"] "F#" "Exe")
        write temp "Probe.fs" """
        module Probe
        open System
        open System.Threading
        open System.Threading.Tasks
        let ensure b m = if not b then failwith m
        let signal () = TaskCompletionSource<unit>(TaskCreationOptions.RunContinuationsAsynchronously)
        let wait (t: Task) = task {
            let! winner = Task.WhenAny(t, Task.Delay(5000))
            ensure (obj.ReferenceEquals(winner, t)) "Concurrent operation did not reach barrier"
            do! t
        }
        let exercise failure reverse = task {
            use caller = new CancellationTokenSource()
            let startedA, startedB, trigger, cleanupStarted, cleanupRelease = signal(), signal(), signal(), signal(), signal()
            let mutable disposedA = false
            let mutable disposedB = false
            let mutable siblingToken = CancellationToken.None
            let mutable tokens = []
            let gate = obj()
            let record token = lock gate (fun () -> tokens <- token :: tokens)
            let first (token: CancellationToken) = task {
                use resource = { new IDisposable with member _.Dispose() = disposedA <- true }
                record token
                startedA.SetResult(())
                do! trigger.Task
                if failure then return raise (InvalidOperationException("original boom"))
                else
                    do! Task.Delay(Timeout.Infinite, token)
                    return 1
            }
            let second (token: CancellationToken) = task {
                siblingToken <- token
                use resource = { new IDisposable with member _.Dispose() = disposedB <- true }
                record token
                startedB.SetResult(())
                try
                    do! Task.Delay(Timeout.Infinite, token)
                with :? OperationCanceledException -> ()
                cleanupStarted.SetResult(())
                do! cleanupRelease.Task
                return 2
            }
            let running =
                if reverse then Ownership.runBoth second first caller.Token
                else Ownership.runBoth first second caller.Token
            try
                do! wait startedA.Task
                do! wait startedB.Task
                ensure (tokens.Length = 2 && tokens |> List.forall (fun t -> t.CanBeCanceled)) "Both operations must receive cancellable tokens"
                trigger.SetResult(())
                if not failure then caller.Cancel()
                do! wait cleanupStarted.Task
                ensure (not running.IsCompleted) "runBoth returned while sibling cleanup was active"
                cleanupRelease.SetResult(())
                let mutable observed = false
                try
                    let! _ = running.WaitAsync(TimeSpan.FromSeconds(5.0))
                    ()
                with
                | :? InvalidOperationException as e when failure && e.Message = "original boom" -> observed <- true
                | :? OperationCanceledException when not failure -> observed <- true
                ensure observed "Expected original failure or caller cancellation"
                ensure (disposedA && disposedB) "Resources were not both disposed before return"
                ensure (if failure then siblingToken.IsCancellationRequested else tokens |> List.forall (fun t -> t.IsCancellationRequested)) "Cancellation did not reach the required operations"
            finally
                caller.Cancel()
                trigger.TrySetResult(()) |> ignore
                cleanupRelease.TrySetResult(()) |> ignore
        }
        let success () = task {
            let startedA, startedB, release = signal(), signal(), signal()
            let operation (started: TaskCompletionSource<unit>) value (_: CancellationToken) = task {
                started.SetResult(())
                do! release.Task
                return value
            }
            let result = Ownership.runBoth (operation startedA 7) (operation startedB 11) CancellationToken.None
            do! wait startedA.Task
            do! wait startedB.Task
            release.SetResult(())
            let! pair = result.WaitAsync(TimeSpan.FromSeconds(5.0))
            ensure (pair = (7, 11)) "Results must retain argument order"
        }
        [<EntryPoint>]
        let main _ =
            try
                (task {
                    do! success ()
                    do! exercise true false
                    do! exercise true true
                    do! exercise false false
                    do! exercise false true
                }).GetAwaiter().GetResult()
                0
            with e -> eprintfn "%s" e.Message; 1
        """
        succeed temp ["run"; "--project"; "Hidden.fsproj"; "--verbosity"; "quiet"] "Async ownership behavior failed"
    with error ->
        eprintfn "%s" (clean error.Message)
        status <- 1
finally
    if Directory.Exists(temp) then Directory.Delete(temp, true)
exit status
