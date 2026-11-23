@echo off
rem Windows launcher: uploader go
pushd "%~dp0" && python -m upload_bot %* & popd
