$ErrorActionPreference='Stop'
$w=[Runtime.InteropServices.Marshal]::GetActiveObject('Kwps.Application')
$d=$w.ActiveDocument
if($d.FullName -ne 'D:\wkplace\auto\mathtype-conversion-working.docx'){throw 'Wrong document'}
$d.Close(0)
$d=$w.Documents.Open('D:\wkplace\auto\mathtype-conversion-working.docx')
$d.Activate()
$w.Run('IsDLLVersionOK')
$n=$d.OMaths.Count
$r=$d.OMaths.Item($n).Range
$x=$r.WordOpenXML
$r.Select()
Write-Output ('Converted='+$w.Run('InsertMTEqnFromOMML',$r,$x))
Write-Output ('Remaining='+$d.OMaths.Count+' Shapes='+$d.InlineShapes.Count)