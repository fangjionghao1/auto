$w=[Runtime.InteropServices.Marshal]::GetActiveObject('Kwps.Application')
$d=$w.Documents.Item(2)
$out=@()
for($i=1;$i -le $d.OMaths.Count;$i++){$r=$d.OMaths.Item($i).Range; $out+= [pscustomobject]@{index=$i;text=$r.Text;xml=$r.WordOpenXML;mml=$w.Run('XformOMML2MML',$r.WordOpenXML)}}
$out | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 'D:\wkplace\auto\equation-audit.json'