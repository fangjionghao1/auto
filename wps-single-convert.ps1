$ErrorActionPreference='Stop'
$w=[Runtime.InteropServices.Marshal]::GetActiveObject('Kwps.Application')
$src=$w.ActiveDocument.FullName
$dst='D:\wkplace\auto\mathtype-conversion-working.docx'
if (!(Test-Path $dst)) { Copy-Item -LiteralPath $src -Destination $dst }
$d=$w.Documents.Open($dst)
$d.Activate()
Write-Output ('Init='+$w.Run('IsDLLVersionOK'))
$n=$d.OMaths.Count
$r=$d.OMaths.Item($n).Range
$x=$r.WordOpenXML
Write-Output ('Before='+$n+' XML='+$x.Length)
Write-Output ('Converted='+$w.Run('InsertMTEqnFromOMML',$r,$x))
Write-Output ('After='+$d.OMaths.Count+' Shapes='+$d.InlineShapes.Count)