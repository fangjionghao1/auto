<#
.SYNOPSIS
  Batch-convert all OMML (Equation Builder) equations in a WPS Writer
  document into MathType-editable OLE equations.

.PARAMETER DocPath
  Full path to the .docx file. If omitted, the currently active WPS
  document is used. If the file is not open in WPS yet, it is opened.

.DESCRIPTION
  Calls the MathType add-in macro DoConvertEquations (shipped inside
  "MathType Commands 2016.dotm") with:
      equationTypes  = 8    -> only OMML equations
      selectionOnly  = 0    -> whole document
      promptUser     = 0    -> no per-equation dialogs
      translatorName = ""   -> convert TO MathType OLE objects

  Safety: the on-disk file is backed up (timestamped .bak) BEFORE the
  conversion. The converted document stays open in WPS; the caller must
  review it and save manually (Ctrl+S). Nothing is auto-saved.

  Exit codes: 0 = success (or nothing to do), 1 = fatal error,
              2 = finished but OMML equations remain.

.NOTES
  Requires: 32-bit MathType add-in working in WPS (MathPage.wll +
  MathType Commands 2016.dotm in WPS office6\startup) and a running
  WPS Writer instance. Windows PowerShell 5.1 compatible.
#>
param(
    [string]$DocPath = ""
)

$ErrorActionPreference = "Stop"

# --- 1. Attach to the running WPS Writer instance --------------------------
Write-Host "[1/5] Attaching to WPS Writer (Kwps.Application) ..."
try {
    $wps = [Runtime.InteropServices.Marshal]::GetActiveObject("Kwps.Application")
} catch {
    Write-Error "WPS Writer is not running. Open WPS Writer first, then re-run this script."
    exit 1
}

# --- 2. Resolve the target document ----------------------------------------
$doc = $null
if ($DocPath -ne "") {
    if (-not (Test-Path -LiteralPath $DocPath)) {
        Write-Error "File not found: $DocPath"
        exit 1
    }
    $full = (Resolve-Path -LiteralPath $DocPath).Path
    foreach ($d in $wps.Documents) {
        if ($d.FullName -ieq $full) { $doc = $d; break }
    }
    if ($null -eq $doc) {
        Write-Host "[2/5] Opening document in WPS: $full"
        $doc = $wps.Documents.Open($full)
    } else {
        Write-Host "[2/5] Document already open: $full"
    }
} else {
    if ($wps.Documents.Count -lt 1) {
        Write-Error "No document is open in WPS Writer and no -DocPath was given."
        exit 1
    }
    $doc = $wps.ActiveDocument
    Write-Host "[2/5] Using active document: $($doc.FullName)"
}
try { $wps.Visible = $true } catch {}
try { $doc.Activate() } catch {}

# --- 3. Count OMML equations ------------------------------------------------
$total = $doc.OMaths.Count
Write-Host "[3/5] OMML equations found: $total"
if ($total -eq 0) {
    Write-Host "RESULT total=0 remaining=0 backup=none"
    exit 0
}

# --- 4. Back up the on-disk file --------------------------------------------
$src   = $doc.FullName
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$bak   = "$src.omml-backup-$stamp.bak"
Write-Host "[4/5] Backing up to: $bak"
Copy-Item -LiteralPath $src -Destination $bak -Force

# --- 5. Run the MathType conversion macro ------------------------------------
Write-Host "[5/5] Converting OMML -> MathType OLE (DoConvertEquations) ..."
$count = 0L
# Run MacroName, showStats, equationTypes, selectionOnly, promptUser,
#                 translatorName, translatorOptions, count
$wps.Run("DoConvertEquations", $false, 8, $false, $false, "", 0, $count)

$left = $doc.OMaths.Count
Write-Host "RESULT total=$total remaining=$left backup=$bak"
Write-Host "Review the document in WPS, then press Ctrl+S to save."
if ($left -eq 0) { exit 0 } else { exit 2 }
