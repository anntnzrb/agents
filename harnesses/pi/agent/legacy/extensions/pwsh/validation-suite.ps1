$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$results = [System.Collections.Generic.List[object]]::new()

function Add-Result {
    param(
        [string]$Name,
        [string]$Status,
        [string]$Details
    )
    $results.Add([pscustomobject]@{
        name = $Name
        status = $Status
        details = $Details
    }) | Out-Null
}

function Test-Case {
    param(
        [string]$Name,
        [scriptblock]$Body
    )

    try {
        $details = & $Body
        if ($null -eq $details) { $details = '' }
        Add-Result -Name $Name -Status 'PASS' -Details ([string]$details)
    }
    catch {
        Add-Result -Name $Name -Status 'FAIL' -Details $_.Exception.Message
    }
}

function Skip-Case {
    param(
        [string]$Name,
        [string]$Reason
    )
    Add-Result -Name $Name -Status 'SKIP' -Details $Reason
}

$root = Join-Path ([System.IO.Path]::GetTempPath()) ("pi-pwsh-suite-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $root | Out-Null

try {
    Test-Case 'short.simple-output' {
        $value = 'ok'
        if ($value -ne 'ok') { throw 'unexpected value' }
        'ok'
    }

    Test-Case 'medium.pipeline-math' {
        $sum = (1..100 | Measure-Object -Sum).Sum
        if ($sum -ne 5050) { throw "expected 5050 got $sum" }
        "sum=$sum"
    }

    Test-Case 'long.multiline-file-workload' {
        $file = Join-Path $root 'long.txt'
        $lines = 1..800 | ForEach-Object { "line $_ :: $('x' * 20)" }
        Set-Content -LiteralPath $file -Value $lines -Encoding utf8
        $count = (Get-Content -LiteralPath $file).Count
        if ($count -ne 800) { throw "expected 800 lines got $count" }
        "lines=$count"
    }

    Test-Case 'quote.single-quote-literal' {
        $text = 'literal $HOME and `backtick` and "double"'
        if ($text -ne 'literal $HOME and `backtick` and "double"') { throw 'single quote literal mismatch' }
        $text
    }

    Test-Case 'quote.double-quote-interpolation' {
        $name = 'neo'
        $text = "hello $name"
        if ($text -ne 'hello neo') { throw "expected hello neo got $text" }
        $text
    }

    Test-Case 'quote.escaped-double-quote' {
        $text = "a `"quoted`" value"
        if ($text -ne 'a "quoted" value') { throw "escaped quote mismatch: $text" }
        $text
    }

    Test-Case 'quote.escape-dollar-in-double' {
        $text = "price is `$5"
        if ($text -ne 'price is $5') { throw "dollar escape mismatch: $text" }
        $text
    }

    Test-Case 'quote.herestring-double' {
        $name = 'agent'
        $text = @"
line1
hello $name
line3
"@
        if ($text -notmatch 'hello agent') { throw 'double here-string interpolation failed' }
        ($text -split "`n")[1]
    }

    Test-Case 'quote.herestring-single' {
        $text = @'
line1
hello $name
line3
'@
        if ($text -notmatch 'hello \$name') { throw 'single here-string should be literal' }
        ($text -split "`n")[1]
    }

    Test-Case 'special.backtick-line-continuation' {
        $value = 'ab' + `
            'cd'
        if ($value -ne 'abcd') { throw "line continuation mismatch: $value" }
        $value
    }

    Test-Case 'special.subexpression-interpolation' {
        $n = 41
        $text = "answer: $($n + 1)"
        if ($text -ne 'answer: 42') { throw "subexpression mismatch: $text" }
        $text
    }

    Test-Case 'path.space-and-unicode-literalpath' {
        $dir = Join-Path $root 'dir with spaces'
        $null = New-Item -ItemType Directory -Path $dir
        $file = Join-Path $dir 'unicodé 🧪 [abc].txt'
        Set-Content -LiteralPath $file -Value 'hello' -Encoding utf8
        $value = Get-Content -LiteralPath $file -Raw
        if ($value.Trim() -ne 'hello') { throw 'literal path read mismatch' }
        Split-Path -Leaf $file
    }

    Test-Case 'concat.semicolon-chain' {
        $a = 1; $a += 2; $a += 3
        if ($a -ne 6) { throw "expected 6 got $a" }
        "a=$a"
    }

    Test-Case 'concat.newline-chain' {
        $a = 1
        $a += 2
        $a += 3
        if ($a -ne 6) { throw "expected 6 got $a" }
        "a=$a"
    }

    Test-Case 'pipeline.objects-filter-map' {
        $items = @(Get-ChildItem -LiteralPath $root | Where-Object { $_.PSIsContainer -eq $false } | Select-Object -ExpandProperty Name)
        if ($items.Count -lt 1) { throw 'expected at least one file in pipeline result' }
        "files=$($items.Count)"
    }

    Test-Case 'pipeline.measurement' {
        $sum = (1..5 | ForEach-Object { $_ * 2 } | Measure-Object -Sum).Sum
        if ($sum -ne 30) { throw "expected 30 got $sum" }
        "sum=$sum"
    }

    Test-Case 'chain.and-operator' {
        $out = (& { 'A' }) && (& { 'B' })
        $joined = ($out -join ',')
        if ($joined -ne 'A,B') { throw "expected A,B got $joined" }
        $joined
    }

    Test-Case 'chain.or-operator' {
        $out = (& pwsh -NoProfile -Command 'exit 1') || (& { 'RECOVER' })
        $joined = ($out -join ',')
        if ($joined -notmatch 'RECOVER') { throw "expected RECOVER got $joined" }
        $joined
    }

    Test-Case 'file.create-and-overwrite' {
        $file = Join-Path $root 'file_ops.txt'
        Set-Content -LiteralPath $file -Value 'one' -Encoding utf8
        Set-Content -LiteralPath $file -Value 'two' -Encoding utf8
        $value = (Get-Content -LiteralPath $file -Raw).Trim()
        if ($value -ne 'two') { throw "expected two got $value" }
        $value
    }

    Test-Case 'file.append' {
        $file = Join-Path $root 'append.txt'
        Set-Content -LiteralPath $file -Value 'a' -Encoding utf8
        Add-Content -LiteralPath $file -Value 'b' -Encoding utf8
        $lines = Get-Content -LiteralPath $file
        if ($lines.Count -ne 2) { throw "expected 2 lines got $($lines.Count)" }
        ($lines -join ',')
    }

    Test-Case 'file.copy-and-move' {
        $source = Join-Path $root 'move_source.txt'
        $copy = Join-Path $root 'move_copy.txt'
        $dest = Join-Path $root 'move_dest.txt'
        Set-Content -LiteralPath $source -Value 'payload' -Encoding utf8
        Copy-Item -LiteralPath $source -Destination $copy -Force
        Move-Item -LiteralPath $copy -Destination $dest -Force
        if (-not (Test-Path -LiteralPath $dest)) { throw 'dest file missing after move' }
        if (Test-Path -LiteralPath $copy) { throw 'copy file still exists after move' }
        (Get-Content -LiteralPath $dest -Raw).Trim()
    }

    Test-Case 'file.json-roundtrip' {
        $file = Join-Path $root 'data.json'
        $obj = [pscustomobject]@{ a = 1; b = 'two'; c = @('x','y') }
        $obj | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $file -Encoding utf8
        $back = Get-Content -LiteralPath $file -Raw | ConvertFrom-Json
        if ($back.a -ne 1 -or $back.b -ne 'two' -or $back.c.Count -ne 2) { throw 'json roundtrip mismatch' }
        'json-ok'
    }

    Test-Case 'encoding.utf8-emoji' {
        $file = Join-Path $root 'utf8.txt'
        $text = 'áéíóú 中文 🧪 🚀'
        $text | Out-File -LiteralPath $file -Encoding utf8
        $back = Get-Content -LiteralPath $file -Raw
        if ($back.Trim() -ne $text) { throw 'utf8 roundtrip mismatch' }
        'utf8-ok'
    }

    Test-Case 'wildcard.literalpath-safety' {
        $file = Join-Path $root '[abc].txt'
        Set-Content -LiteralPath $file -Value 'ok' -Encoding utf8
        $value = (Get-Content -LiteralPath $file -Raw).Trim()
        if ($value -ne 'ok') { throw 'literalpath wildcard file mismatch' }
        $value
    }

    Test-Case 'native.commandwithargs-escaping' {
        if ($PSVersionTable.PSVersion -lt [Version]'7.4.0') {
            throw 'CommandWithArgs requires PowerShell >= 7.4'
        }
        $out = & pwsh -NoProfile -CommandWithArgs '$args -join "|"' 'a b' 'c"d' "e'f" '$x'
        $expected = "a b|c`"d|e'f|`$x"
        if ($out -ne $expected) {
            throw "expected [$expected] got [$out]"
        }
        $out
    }

    if ($IsWindows) {
        Test-Case 'windows.stop-parsing-operator' {
            $out = & cmd /c 'echo a^&b'
            if (-not $out) { throw 'cmd output empty' }
            'cmd-ok'
        }

        Test-Case 'windows.native-path-backslashes' {
            $winPath = Join-Path $env:TEMP 'pwsh-win-test'
            if ($winPath -notmatch '\\') { throw "expected backslashes in path: $winPath" }
            $winPath
        }

        Test-Case 'windows.legacy-powershell-availability' {
            $exe = Get-Command powershell.exe -ErrorAction Stop
            $major = & powershell.exe -NoProfile -NonInteractive -Command '$PSVersionTable.PSVersion.Major'
            if (-not $major) { throw 'powershell.exe returned empty version' }
            "path=$($exe.Source);major=$major"
        }
    }
    else {
        Skip-Case -Name 'windows.stop-parsing-operator' -Reason 'Non-Windows host'
        Skip-Case -Name 'windows.native-path-backslashes' -Reason 'Non-Windows host'
        Skip-Case -Name 'windows.legacy-powershell-availability' -Reason 'Non-Windows host'
    }

    Test-Case 'cleanup.tmp-tree-removable' {
        $probeDir = Join-Path $root 'cleanup-probe'
        $probeFile = Join-Path $probeDir 'x.txt'
        New-Item -ItemType Directory -Path $probeDir | Out-Null
        Set-Content -LiteralPath $probeFile -Value 'x' -Encoding utf8
        Remove-Item -LiteralPath $probeDir -Recurse -Force
        if (Test-Path -LiteralPath $probeDir) { throw 'cleanup probe directory still exists' }
        'cleanup-ok'
    }
}
finally {
    if (Test-Path -LiteralPath $root) {
        Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    }
}

$pass = @($results | Where-Object { $_.status -eq 'PASS' }).Count
$fail = @($results | Where-Object { $_.status -eq 'FAIL' }).Count
$skip = @($results | Where-Object { $_.status -eq 'SKIP' }).Count

[pscustomobject]@{
    host = [pscustomobject]@{
        pwshVersion = $PSVersionTable.PSVersion.ToString()
        os = [System.Runtime.InteropServices.RuntimeInformation]::OSDescription
        isWindows = [bool]$IsWindows
        isLinux = [bool]$IsLinux
        isMacOS = [bool]$IsMacOS
    }
    summary = [pscustomobject]@{
        total = $results.Count
        pass = $pass
        fail = $fail
        skip = $skip
    }
    results = $results
} | ConvertTo-Json -Depth 8
