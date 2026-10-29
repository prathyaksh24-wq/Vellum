"""Install declarative user plugins through PluginRegistry; never execute uploads."""
import base64
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import zipfile

import yaml

from agent.contracts.plugin_setup import PluginSetup
from agent.plugins.sources import CodexPluginSource
from agent.skills.parser import SkillPackageParser
from agent.skills.security import SkillSecurityScanner


def add_plugin(registry, request: PluginSetup):
    plugin_id='custom-'+re.sub('[^a-z0-9]+','-',request.name.casefold()).strip('-')
    if plugin_id=='custom-' or registry.contains(plugin_id):
        raise ValueError('Choose a unique plugin name.')
    registry.root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.plugin-setup-',dir=registry.root.parent) as scratch:
        stage=Path(scratch)
        manifest={'id':plugin_id,'name':request.name.strip(),'type':'bundle','category':'Personal','version':'1.0.0',
            'description':request.description,'apps':[],'mcp_connectors':[]}
        if request.kind=='mcp':
            connector={'name':plugin_id,'transport':request.transport}
            if request.transport=='http':connector['url']=request.url
            else:connector.update(command=request.command,args=request.args)
            if request.env:connector['env']=request.env
            if request.headers:connector['headers']=request.headers
            manifest.update(type='mcp',category='MCP',mcp_connectors=[connector])
        if request.kind=='archive':
            try: raw=base64.b64decode(request.archive_b64,validate=True)
            except ValueError: raise ValueError('Choose a valid ZIP plugin archive.') from None
            if len(raw)>2*1024*1024:raise ValueError('Plugin archives must be 2 MiB or smaller.')
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                infos=archive.infolist()
                if len(infos)>250 or sum(info.file_size for info in infos)>4*1024*1024:
                    raise ValueError('The plugin archive exceeds the package limits.')
                for info in infos:
                    relative=PurePosixPath(info.filename.replace('\\','/'))
                    if relative.is_absolute() or '..' in relative.parts or ':' in info.filename or (info.external_attr>>16)&0o170000==0o120000:
                        raise ValueError('The archive contains an unsafe path or symlink.')
                    if info.is_dir():continue
                    if info.file_size>512000:raise ValueError('A plugin file exceeds the size limit.')
                    content=archive.read(info).decode('utf-8')
                    target=stage.joinpath(*relative.parts)
                    target.parent.mkdir(parents=True,exist_ok=True);target.write_text(content,encoding='utf-8')
            manifests=list(stage.rglob('plugin.yaml'))+list(stage.rglob('.codex-plugin/plugin.json'))
            if len(manifests)!=1:raise ValueError('The archive must contain one plugin.yaml or .codex-plugin/plugin.json manifest.')
            entry=manifests[0]
            root=entry.parent if entry.name=='plugin.yaml' else entry.parent.parent
            if entry.name=='plugin.yaml':
                data=yaml.safe_load(entry.read_text(encoding='utf-8')) or {}
                if data.get('provides_tools'):raise ValueError('Executable Python plugins are unsupported by archive upload. Use a declarative MCP or skill bundle.')
                connectors=data.get('mcp_connectors') or []
                skills=root/'skills'
                manifest.update(description=str(data.get('description') or '')[:500],apps=data.get('apps') or [])
            else:
                record=CodexPluginSource([])._read(entry)
                connectors=record.mcp_connectors;skills=record.skills_root
                manifest.update(description=record.description[:500],apps=record.apps)
            validated=[]
            for item in connectors:
                transport='http' if item.get('url') else 'stdio'
                config=PluginSetup(kind='mcp',name=str(item.get('name') or plugin_id),transport=transport,
                    url=str(item.get('url') or ''),command=str(item.get('command') or ''),args=item.get('args') or [],env=item.get('env') or {},headers=item.get('headers') or {})
                validated.append({'name':config.name,'transport':transport,**({'url':config.url} if transport=='http' else {'command':config.command,'args':config.args}),
                    **({'env':config.env} if config.env else {}),**({'headers':config.headers} if config.headers else {})})
            manifest['mcp_connectors']=validated
            publish=stage/'publish';publish.mkdir()
            if skills and skills.is_dir():
                for file in list(skills.rglob('SKILL.md')):
                    package=SkillPackageParser().parse(file.parent)
                    scan=SkillSecurityScanner().scan(file.parent,source='uploaded-plugin',trust_level='community')
                    if scan.verdict!='safe':raise ValueError('A skill in the archive needs review before it can be imported.')
                    shutil.copytree(package.root,publish/'skills'/package.metadata.name)
            stage=publish
        # Only the declarative manifest and scanned skills are published, never uploaded code.
        (stage/'plugin.yaml').write_text(yaml.safe_dump(manifest,sort_keys=False),encoding='utf-8')
        (stage/'__init__.py').write_text('def register(ctx):\n    pass\n',encoding='utf-8')
        destination=registry.root/'custom'/plugin_id
        destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists():raise ValueError('This plugin already exists.')
        # Same-volume rename publishes the reviewed package together.
        stage.rename(destination)
        registry._source_records_cache=None
    return registry.describe(plugin_id)
