$out = Split-Path -Parent $MyInvocation.MyCommand.Path
$tabs = @('INDUK','NIBONG','BERTAM','JAMBUL','KUBANG')

function Parse-CsvLine($line) {
    $result = @()
    $cur = ""
    $inQ = $false
    foreach ($ch in $line.ToCharArray()) {
        if ($ch -eq '"') { $inQ = -not $inQ; continue }
        if ($ch -eq ',' -and -not $inQ) { $result += $cur; $cur = ""; continue }
        $cur += $ch
    }
    $result += $cur
    return $result
}

function Analyze-Tab($name) {
    $path = Join-Path $out "$name.csv"
    $raw = Get-Content $path -Raw
    $lines = $raw -split "`r?`n"
    $rows = foreach ($ln in $lines) { if ($ln) { Parse-CsvLine $ln } }

    $hdrIdx = -1
    for ($i = 0; $i -lt [Math]::Min($rows.Count, 5); $i++) {
        $hasTrunk = ($rows[$i] | Where-Object { $_.Trim().Replace("`r",'') -eq 'Trunking' }).Count -gt 0
        if ($hasTrunk) { $hdrIdx = $i; break }
    }

    $issues = @()
    if ($hdrIdx -lt 0) { return [PSCustomObject]@{ Tab=$name; Issues='No Trunking header' } }

    $hdr = @($rows[$hdrIdx] | ForEach-Object { $_.Trim().Replace("`r",'') })
    $locCol = if ($hdr[0] -match '^(LOCATION|Location)$') { 0 } elseif ($hdr[1] -match '^(LOCATION|Location)$') { 1 } else { -1 }
    $progCol = $locCol + 1

    if ($locCol -lt 0) { $issues += 'Cannot find LOCATION column' }

    $trunk = @()
    $dates = @()
    for ($i = 0; $i -lt $hdr.Count; $i++) {
        if ($hdr[$i] -eq 'Trunking') { $trunk += $i }
        if ($hdr[$i] -in @('Date','DATE')) { $dates += $i }
    }

    foreach ($ti in $trunk) {
        if ($ti -gt 0) {
            $prev = $hdr[$ti - 1]
            if ($prev -notin @('Date','DATE','')) {
                $issues += "Trunking col ${ti} missing Date before it (prev='$prev')"
            }
        }
    }

    if ($hdrIdx -eq 0 -and $name -ne 'INDUK') { $issues += 'Header on row 1 (most tabs use row 2)' }
    if ($hdrIdx -eq 1 -and $name -eq 'INDUK') { $issues += 'INDUK shifted to row 2 like other tabs' }

    $crDates = ($rows[$hdrIdx] | Where-Object { $_ -match "Date`r" }).Count
    if ($crDates -gt 0) { $issues += "${crDates} Date header(s) have Alt+Enter line break" }

    if (($hdr | Where-Object { $_ -match 'equioments' }).Count -gt 0) { $issues += 'Typo Active equioments' }

    if ($name -eq 'KUBANG' -and $trunk.Count -ge 2) {
        $gap = $trunk[1] - $trunk[0]
        if ($gap -lt 10) { $issues += "First block only $gap cols wide (no Active equipment gap)" }
    }

    $locs = 0
    $badLocs = @()
    $pctLabels = @{}
    $noDateBlock1 = 0
    $mixedDates = @{}

    for ($r = $hdrIdx + 2; $r -lt $rows.Count; $r++) {
        $row = $rows[$r]
        if ($row.Count -le $progCol) { continue }
        $loc = $row[$locCol].Trim()
        $prog = $row[$progCol].Trim().ToUpper()

        if ($prog -eq 'DONE' -and $loc) {
            $locs++
            if ($loc -match "[\r\n]" -or ($loc -match '^"' -and $loc.Length -gt 1)) {
                $badLocs += ($loc -replace "[\r\n]", ' ')
            }
            $dCol = $progCol + 1
            if ($dCol -lt $row.Count) {
                $dv = $row[$dCol].Trim()
                if ($dv -notmatch '^\d{1,2}/\d{1,2}/\d{2,4}$') { $noDateBlock1++ }
                else { $mixedDates[$dv] = $true }
            }
        }
        if ($prog -in @('PERCENT','PERCENTAGE')) {
            if (-not $pctLabels.ContainsKey($prog)) { $pctLabels[$prog] = 0 }
            $pctLabels[$prog]++
        }
    }

    if ($pctLabels.ContainsKey('PERCENT') -and $pctLabels.ContainsKey('PERCENTAGE')) {
        $issues += "Mixed PERCENT ($($pctLabels['PERCENT'])) and PERCENTAGE ($($pctLabels['PERCENTAGE'])) rows"
    }

    [PSCustomObject]@{
        Tab = $name
        HeaderRow = $hdrIdx + 1
        LocCol = "col $($locCol + 1)"
        TrunkingBlocks = $trunk.Count
        DateHeaders = $dates.Count
        Locations = $locs
        PercentLabel = ($pctLabels.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ', '
        MissingDateOnDone = $noDateBlock1
        BadLocationNames = if ($badLocs.Count) { ($badLocs | Select-Object -Unique) -join ' | ' } else { 'none' }
        DateFormats = ($mixedDates.Keys | Select-Object -First 8) -join ', '
        Issues = if ($issues.Count) { $issues -join '; ' } else { 'none detected' }
    }
}

$tabs | ForEach-Object { Analyze-Tab $_ } | Format-Table -AutoSize -Wrap
