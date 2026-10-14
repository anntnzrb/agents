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
let original = "namespace Cascades\n\ntype Customer = { Name: string; Code: int }\ntype Shipment = { Name: string; Code: string }\n\nmodule Pipeline =\n    let normalize text = text.Trim().ToUpperInvariant()\n\n    let customerCode entry = entry.Code + 100\n\n    let labels (customers: Customer list) =\n        customers\n        |> List.map (fun customer -> normalize customer.Name, customerCode customer)\n\n    let shipmentLabels (shipments: Shipment list) =\n        shipments |> List.map (fun shipment -> normalize shipment.Name, shipment.Code)\n\n    let summarize customers shipments =\n        labels customers, shipmentLabels shipments\n"
let distance (left: string array) (right: string array) =
    let previous = Array.init (right.Length + 1) id
    for i in 1 .. left.Length do
        let current = Array.zeroCreate (right.Length + 1)
        current.[0] <- i
        for j in 1 .. right.Length do
            current.[j] <- min (previous.[j] + 1) (min (current.[j-1] + 1) (previous.[j-1] + if left.[i-1] = right.[j-1] then 0 else 1))
        Array.Copy(current, previous, current.Length)
    previous.[right.Length]
let grade dir =
    require (read dir "Pipeline.fsproj" = "<Project Sdk=\"Microsoft.NET.Sdk\">\n  <PropertyGroup>\n    <TargetFramework>net10.0</TargetFramework>\n    <GenerateDocumentationFile>true</GenerateDocumentationFile>\n  </PropertyGroup>\n  <ItemGroup>\n    <Compile Include=\"Pipeline.fs\" />\n  </ItemGroup>\n\n</Project>\n") "Keep the project settings and compile inputs unchanged"
    let source = read dir "Pipeline.fs"
    require (distance (original.Split('\n')) (source.Split('\n')) <= 8) "The fix exceeds eight source-line edits"
    let sources = Directory.GetFiles(dir, "*.fs", SearchOption.AllDirectories)
    require (sources.Length = 1) "Do not replace the local inference fixes with added source files"
    require (not (Regex.IsMatch(source + read dir "Pipeline.fsproj", @"\bobj\b|\bobject\b|:\?>|#nowarn|NoWarn"))) "Object types, downcasts, or warning suppression were added"
    build dir "Pipeline.fsproj" "Debug"
    checkFsi dir "hidden-behavior.fsx" "#r \"bin/Debug/net10.0/Pipeline.dll\"\nopen Cascades\nlet customers : Customer list = [{ Name = \"  Ana \"; Code = 7 }; { Name = \"bob\"; Code = -100 }]\nlet shipments : Shipment list = [{ Name = \" south \"; Code = \"007\" }; { Name = \"nOrTh\"; Code = \"x\" }]\nlet result = Pipeline.summarize customers shipments\nif result <> ([\"ANA\", 107; \"BOB\", 0], [\"SOUTH\", \"007\"; \"NORTH\", \"x\"]) then failwith \"Pipeline behavior changed\"\nif Pipeline.summarize [] [] <> ([], []) then failwith \"Empty input changed\"\nif Pipeline.normalize \" AbC \" <> \"ABC\" then failwith \"Normalization changed\"\nif Pipeline.customerCode { Name = \"test\"; Code = 21 } <> 121 then failwith \"Customer codes changed\"\n" "Hidden pipeline behavior checks failed"

main grade
