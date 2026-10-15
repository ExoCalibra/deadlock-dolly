@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
cl /nologo /EHsc /std:c++17 /I native\include native\tests\lite_policy_tests.cpp /Fe:ui-preview\LitePolicyTests.exe
