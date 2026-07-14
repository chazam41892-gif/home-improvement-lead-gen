import sys
sys.path.insert(0, str(__import__('pathlib').Path.home() / '.lvtn'))
from unified_vault import UnifiedVault

uv = UnifiedVault.instance()
all_svcs = uv.list_all()
print('UnifiedVault services:', len(all_svcs))
for svc_id, info in all_svcs.items():
    if info['configured']:
        print('  ' + svc_id + ': configured=' + str(info['configured']) + ', keys=' + str(info['keys']))