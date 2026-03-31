Write-Host "Waiting for any currently running python script to finish saving its Excel file..."
while (Get-Process python -ErrorAction SilentlyContinue) {
    Start-Sleep -Seconds 10
}

Write-Host "`n✅ The previous batch is completely done and saved!"
Write-Host "🚀 Taking over automatically to process the remaining rows..."

$env:PYTHONIOENCODING='utf-8'
while ($true) {
    Write-Host "`n--- STARTING NEXT BATCH ---"
    $output = & python -u linkedin_apify_batch.py
    
    # Print the output so we can see it
    $outputString = $output | Out-String
    Write-Host $outputString
    
    if ($outputString -match "No unprocessed rows left") {
        Write-Host "🎉 ALL PROFILES HAVE BEEN SUCCESSFULLY PROCESSED AND SAVED! Enjoy your lunch!"
        break
    }
    
    Write-Host "Waiting 5 seconds before starting next batch..."
    Start-Sleep -Seconds 5
}
