$ErrorActionPreference='Stop'
$w=[Runtime.InteropServices.Marshal]::GetActiveObject('Kwps.Application')
$d=$w.ActiveDocument
if($d.FullName -ne 'D:\wkplace\auto\mathtype-conversion-working.docx'){throw 'Wrong document'}
$w.Run('IsDLLVersionOK') | Out-Null
$done=1
while($d.OMaths.Count -gt 0){
 $before=$d.OMaths.Count
 $r=$d.OMaths.Item($before).Range
 $m=$w.Run('XformOMML2MML',$r.WordOpenXML)
 if(!$m -or $m -eq 'omml_xform_error'){throw 'MathML transformation failed'}
 $pos=$r.Start
 $r.Delete() | Out-Null
 $r=$d.Range($pos,$pos)
 $r.InsertFile('D:\math\anzhuang\Office Support\BlankEqn.doc','MTBlankEqn')
 $s=$null
 foreach($a in $d.InlineShapes){if($a.Type -eq 1 -and $a.Range.Start -eq $pos){$s=$a;break}}
 if($null -eq $s){throw ('Inserted object not found at '+$pos)}
 $s.Range.Select()
 $ok=$w.Run('SetMTData',$s,$m)
 if(!$ok){throw ('SetMTData failed at '+$pos)}
 if($d.OMaths.Count -ne ($before-1)){throw 'Equation count mismatch'}
 $done++
 if($done % 10 -eq 0){Write-Output ('Converted='+$done+' Remaining='+$d.OMaths.Count)}
}
$ole=0
foreach($a in $d.InlineShapes){if($a.Type -eq 1 -and $a.OLEFormat.ClassType -eq 'Equation.DSMT4'){$ole++}}
Write-Output ('RESULT OMML='+$d.OMaths.Count+' MathTypeOLE='+$ole+' Saved='+$d.Saved)
$d.Range(0,0).Select()