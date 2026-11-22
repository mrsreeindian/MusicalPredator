Add-Type -AssemblyName System.Runtime.WindowsRuntime
Add-Type -AssemblyName System.Drawing

$asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { 
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' 
}

function AwaitOp($op, $type) {
    $m = $asTaskGeneric.MakeGenericMethod($type)
    $t = $m.Invoke($null, @($op))
    $t.Wait()
    return $t.Result
}

try {
    $asyncOp = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media, ContentType = WindowsRuntime]::RequestAsync()
    $mgr = AwaitOp $asyncOp ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
    $session = $mgr.GetCurrentSession()
    if ($session) {
        $props = AwaitOp ($session.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
        $info = @{
            Title = $props.Title
            Artist = $props.Artist
            AlbumTitle = $props.AlbumTitle
            HasThumbnail = ($props.Thumbnail -ne $null)
        }
        
        if ($props.Thumbnail) {
            $stream = AwaitOp ($props.Thumbnail.OpenReadAsync()) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
            $asStreamMethod = [System.IO.WindowsRuntimeStreamExtensions].GetMethod("AsStream", [Type[]]@([Windows.Storage.Streams.IRandomAccessStream]))
            if ($asStreamMethod) {
                $netStream = $asStreamMethod.Invoke($null, @($stream))
                $outFile = [System.IO.Path]::Combine($PSScriptRoot, "current_album_cover.jpg")
                $fileStream = [System.IO.File]::Create($outFile)
                $netStream.CopyTo($fileStream)
                $fileStream.Close()
                $netStream.Close()
                $info["SavedPath"] = $outFile
            }
        }
        $info | ConvertTo-Json -Compress
    } else {
        '{"NoSession": true}'
    }
} catch {
    Write-Output ("Error: " + $_.Exception.ToString())
}
