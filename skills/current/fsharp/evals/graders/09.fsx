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
        require (File.ReadAllText(Path.Combine(temp, "Inventory.fsi")).Contains("Codes")) "C# facade is missing from the .fsi signature"
        let consumer = Path.Combine(temp, "Consumer")
        Directory.CreateDirectory(consumer) |> ignore
        write consumer "Consumer.csproj" (project ["Program.cs"] ["../Inventory.fsproj"] "C#" "Exe")
        write consumer "Program.cs" """
        using System;
        using System.Linq;
        using System.Reflection;
        using Inventory;
        static class Program
        {
            static void Ensure(bool condition, string reason) { if (!condition) throw new Exception(reason); }
            static bool HasFSharpType(Type t) => (t.Namespace?.StartsWith("Microsoft.FSharp", StringComparison.Ordinal) ?? false) || (t.HasElementType && HasFSharpType(t.GetElementType()!)) || (t.IsGenericType && t.GetGenericArguments().Any(HasFSharpType));
            static int Main()
            {
                try
                {
                    foreach (var input in new[] { "abc", " AbC ", "xyz" })
                    {
                        Ensure(Codes.TryNormalize(input, out string normalized), "Valid code rejected");
                        Ensure(normalized == input.Trim().ToUpperInvariant(), "Normalization incorrect");
                    }
                    foreach (var input in new string?[] { null, "", "ab", "abcd", "a1c", "ábc" })
                        Ensure(!Codes.TryNormalize(input, out string invalid) && invalid == "", "Invalid code accepted or output not cleared");
                    Ensure(Codes.NormalizeAll(new[] { "abc", " XyZ ", "abc" }).SequenceEqual(new[] { "ABC", "XYZ", "ABC" }), "NormalizeAll order/content incorrect");
                    Ensure(Codes.NormalizeAll(Array.Empty<string>()).Count == 0, "Empty input failed");
                    bool rejected = false;
                    try { Codes.NormalizeAll(new[] { "abc", "bad!" }); } catch (ArgumentException) { rejected = true; }
                    Ensure(rejected, "NormalizeAll did not reject invalid item");
                    var exported = typeof(Codes).Assembly.GetExportedTypes().Select(t => t.FullName).OrderBy(n => n);
                    Ensure(exported.SequenceEqual(new[] { "Inventory.Codes", "Inventory.ProductCode", "Inventory.ProductCodeModule" }), "Signature exposes unintended public types");
                    var productModule = typeof(Codes).Assembly.GetType("Inventory.ProductCodeModule")!;
                    Ensure(productModule.GetMethods(BindingFlags.Public | BindingFlags.Static | BindingFlags.DeclaredOnly).Select(m => m.Name).OrderBy(n => n).SequenceEqual(new[] { "tryCreate", "value" }), "Signature exposes unintended ProductCode module members");
                    Ensure(typeof(ProductCode).GetMethods(BindingFlags.Public | BindingFlags.Static | BindingFlags.DeclaredOnly).Length == 0, "Signature exposes unintended ProductCode factories");
                    var methods = typeof(Codes).GetMethods(BindingFlags.Public | BindingFlags.Static | BindingFlags.DeclaredOnly);
                    Ensure(methods.Length == 2 && methods.Select(m => m.Name).OrderBy(n => n).SequenceEqual(new[] { "NormalizeAll", "TryNormalize" }), "Facade exposes unintended public methods");
                    var normalize = methods.Single(m => m.Name == "TryNormalize");
                    var normalizeParameters = normalize.GetParameters();
                    Ensure(normalize.ReturnType == typeof(bool) && normalizeParameters.Length == 2 && normalizeParameters[0].ParameterType == typeof(string) && normalizeParameters[1].ParameterType == typeof(string).MakeByRefType() && normalizeParameters[1].IsOut, "TryNormalize must return bool and accept string input, out string normalized");
                    var all = methods.Single(m => m.Name == "NormalizeAll");
                    Ensure(all.ReturnType == typeof(System.Collections.Generic.IReadOnlyList<string>) && all.GetParameters().Select(p => p.ParameterType).SequenceEqual(new[] { typeof(System.Collections.Generic.IEnumerable<string>) }), "NormalizeAll must accept IEnumerable<string> and return IReadOnlyList<string>");
                    foreach (var method in methods)
                    {
                        Ensure(!HasFSharpType(method.ReturnType), "Facade return type exposes FSharp.Core");
                        Ensure(method.GetParameters().All(p => !HasFSharpType(p.ParameterType)), "Facade parameter exposes FSharp.Core");
                    }
                    Ensure(typeof(ProductCode).GetConstructors().Length == 0, "ProductCode has a public constructor");
                    Ensure(typeof(Codes).GetConstructors().Length == 0, "Static facade must not be constructible");
                    return 0;
                }
                catch (Exception e) { Console.Error.WriteLine(e.Message); return 1; }
            }
        }
        """
        succeed consumer ["run"; "--project"; "Consumer.csproj"; "--verbosity"; "quiet"] "C# facade consumer failed"
        write temp "Forge.fsproj" (project ["Forge.fs"] ["Inventory.fsproj"] "F#" "Library")
        write temp "Forge.fs" "module Forge\nopen Inventory\nlet forged = ProductCode \"invalid!\"\n"
        let code, _ = run temp ["build"; "Forge.fsproj"; "--verbosity"; "quiet"]
        require (code <> 0) "External ProductCode construction bypasses validation"
    with error ->
        eprintfn "%s" (clean error.Message)
        status <- 1
finally
    if Directory.Exists(temp) then Directory.Delete(temp, true)
exit status
