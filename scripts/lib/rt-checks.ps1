# rt-checks.ps1 - which checks scripts\test\run-all-checks.ps1 runs, with no side effect.
#
# Dot-sourced by run-all-checks.ps1 and by scripts\test\verify-branch-tools.ps1.

function Get-RtCheckList {
    <#
        --------------------------------------------------------------------------
        Purpose:
            List, in run order, the scripts that make up "all the checks": the
            offline suite first, then every verify-*.ps1 of that one folder (not other folders) in name
            order. verify-graph-health.ps1 is left out by default because
            vault-access-guard.py refuses it to every caller but local-writer.

        Inputs:
            TestDir (string): the folder holding run-offline-tests.ps1 and verify-*.ps1
            Exclude (string[]): file names to leave out
            Only (string[]): when given, run only these (a name with or without .ps1)
            SkipSuite (switch): leave the offline suite out

        Outputs:
            checks (object[]): Name, Path, Kind ("suite" or "verify")

        Raises:
            ArgumentException: an -Only name matches no check, or the suite script is
            missing when it is wanted. Nothing is skipped silently (R8).
        --------------------------------------------------------------------------
    #>
    param(
        [Parameter(Mandatory = $true)][string]$TestDir,
        [string[]]$Exclude = @(),
        [string[]]$Only = @(),
        [switch]$SkipSuite
    )
    $all = @()
    $suite = Join-Path $TestDir "run-offline-tests.ps1"
    if (-not $SkipSuite) {
        if (-not (Test-Path -LiteralPath $suite -PathType Leaf)) {
            throw [System.ArgumentException]::new("run-offline-tests.ps1 not found in $TestDir")
        }
        $all += [PSCustomObject]@{ Name = "run-offline-tests.ps1"; Path = $suite; Kind = "suite" }
    }
    $verifiers = @(Get-ChildItem -LiteralPath $TestDir -Filter "verify-*.ps1" -File | Sort-Object Name)
    foreach ($file in $verifiers) {
        if ($Exclude -contains $file.Name) { continue }
        $all += [PSCustomObject]@{ Name = $file.Name; Path = $file.FullName; Kind = "verify" }
    }
    if (@($Only).Count -gt 0) {
        $wanted = @()
        foreach ($name in $Only) {
            $full = if ($name.EndsWith(".ps1")) { $name } else { "$name.ps1" }
            $hit = @($all | Where-Object { $_.Name -eq $full })
            if ($hit.Count -eq 0) {
                throw [System.ArgumentException]::new("no check named '$name' (known: $((@($all | ForEach-Object { $_.Name })) -join ', '))")
            }
            $wanted += $hit[0]
        }
        $all = @($all | Where-Object { $wanted.Name -contains $_.Name })
    }
    return $all
}
