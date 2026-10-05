"""Compile only this module with existing SkyFire MSVC settings, without deploying.
Usage: python tests/compile.py <existing-MSVC-build-directory>
All outputs stay under mod-auctionbot/.validation.
"""
from pathlib import Path
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

module = Path(__file__).resolve().parents[1]
if len(sys.argv) != 2:
    raise SystemExit('Usage: python tests/compile.py <existing-MSVC-build-directory>')
build = Path(sys.argv[1]).resolve()
project = build / 'modules/modules.vcxproj'
if not project.is_file():
    raise SystemExit(f'MSVC modules project not found: {project}')
ns = {'m': 'http://schemas.microsoft.com/developer/msbuild/2003'}
root = ET.parse(project).getroot()
group = next(g for g in root.findall('m:ItemDefinitionGroup', ns) if 'Release|x64' in g.get('Condition', ''))
settings = group.find('m:ClCompile', ns)
def setting(name):
    node = settings.find('m:' + name, ns)
    return node.text if node is not None else ''

vswhere = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
vs = subprocess.check_output([str(vswhere), '-latest', '-products', '*', '-property', 'installationPath'], text=True).strip()
vcvars = Path(vs) / 'VC/Auxiliary/Build/vcvars64.bat'
output = module / '.validation'
output.mkdir(exist_ok=True)
arguments = ['/nologo', '/c', '/EHsc', '/MD', '/std:c++17', '/utf-8', '/W3', '/bigobj', '/DNOMINMAX']
for value in setting('PreprocessorDefinitions').split(';'):
    if value and not value.startswith('%') and '$(' not in value:
        arguments.append('/D"' + value.replace('"', '\\"') + '"')
for value in setting('AdditionalIncludeDirectories').split(';'):
    if value and not value.startswith('%'):
        arguments.append('/I"' + value + '"')
arguments.append('/I"' + str(module / 'src') + '"')
test_arguments = [a for a in arguments if a != '/c']
test_arguments += ['/UNDEBUG', '/Fe:item_properties_test.exe', '"' + str(module / 'tests/item_properties_test.cpp') + '"']
(output / 'item_properties_test.rsp').write_text('\n'.join(test_arguments), encoding='utf-8')
arguments.extend('"' + str(p) + '"' for p in sorted((module / 'src').glob('*.cpp')))
(output / 'compile.rsp').write_text('\n'.join(arguments), encoding='utf-8')
(output / 'compile.cmd').write_text('@echo off\ncall "' + str(vcvars) + '" >nul\nif errorlevel 1 exit /b %errorlevel%\ncl.exe @compile.rsp\nif errorlevel 1 exit /b %errorlevel%\ncl.exe /nologo /EHsc /MD /std:c++17 /I"../src" "../tests/policy_test.cpp" /Fe:policy_test.exe\nif errorlevel 1 exit /b %errorlevel%\npolicy_test.exe\nif errorlevel 1 exit /b %errorlevel%\ncl.exe @item_properties_test.rsp\nif errorlevel 1 exit /b %errorlevel%\nitem_properties_test.exe\nexit /b %errorlevel%\n', encoding='utf-8')
result = subprocess.run(['cmd.exe', '/d', '/c', 'compile.cmd'], cwd=output, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
log = result.stdout.decode('utf-8', errors='replace')
(output / 'compile.log').write_text(log, encoding='utf-8')
print(log)
print('Module compile exit code:', result.returncode)
raise SystemExit(result.returncode)
