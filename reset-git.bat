@echo off
SETLOCAL EnableDelayedExpansion

echo ===================================================
echo     TOTAL RESET: WIPING LOCAL AND REMOTE HISTORY   
echo ===================================================

:: 1. Get the current folder name to use as the repo name
for %%I in (.) do set "REPONAME=%%~nxI"
echo [INFO] Target repository name: %REPONAME%

:: 2. Wipe existing remote repository on GitHub if it exists
echo [INFO] Checking for pre-existing remote repository on GitHub...
gh repo delete SayantanD938/%REPONAME% --yes 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [SUCCESS] Previous remote repository deleted from GitHub.
) else (
    echo [INFO] No pre-existing remote repository found on GitHub. Proceeding...
)

:: 3. Wipe existing local Git tracking if present
if exist ".git" (
    echo [INFO] Found existing local .git folder. Wiping...
    attrib -h -s -r ".git" /s /d
    rmdir /s /q ".git"
    echo [SUCCESS] Existing local Git history wiped.
) else (
    echo [INFO] No existing local .git folder found.
)

:: 4. Initialize fresh local repository
echo [INFO] Initializing new Git repository...
git init
git branch -M main

:: 5. Stage and commit all current files
echo [INFO] Staging all files...
git add .

echo [INFO] Creating initial commit...
git commit -m "Initial Commit"

:: 6. Create clean remote repo on GitHub via GH CLI
echo [INFO] Creating clean repository on GitHub...
gh repo create SayantanD938/%REPONAME% --public

:: 7. Link the local repository to the new GitHub remote URL
echo [INFO] Setting up remote origin...
git remote remove origin 2>nul
git remote add origin https://github.com/SayantanD938/%REPONAME%.git

:: 8. Set the default repository for GitHub CLI contexts
gh repo set-default SayantanD938/%REPONAME% 2>nul

:: 9. Push up to GitHub main branch using native git
echo [INFO] Pushing files to GitHub...
git push -u origin main

echo ===================================================
echo [SUCCESS] Process Complete! Everything is fresh.
echo ===================================================
pause