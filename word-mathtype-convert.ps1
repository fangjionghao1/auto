$ErrorActionPreference='Stop'
$src='D:\Users\Administrator\Downloads\R1 会议 基于多头注意力图神经网络的合成径向配电网动态优化控制.docx'
$dst='D:\Users\Administrator\Downloads\R1 会议 基于多头注意力图神经网络的合成径向配电网动态优化控制-MathType.docx'
if(Test-Path -LiteralPath $dst){throw 'Output already exists'}
Copy-Item -LiteralPath $src -Destination $dst
$w=New-Object -ComObject Word.Application
$w.Visible=$true
$d=$w.Documents.Open($dst)
$d.Activate()
Write-Output ('Before='+$d.OMaths.Count)
Write-Output ('Init='+$w.Run('IsDLLVersionOK'))
$count=0L
$w.Run('DoConvertEquations',$false,8,$false,$false,'',0,$count)
Write-Output ('After='+$d.OMaths.Count+' InlineShapes='+$d.InlineShapes.Count)
