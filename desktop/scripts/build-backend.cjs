const {spawnSync}=require('node:child_process');
const path=require('node:path');
const root=path.resolve(__dirname,'../..');
const python=process.env.VELLUM_BUILD_PYTHON || path.join(root,'.venv','Scripts','python.exe');
const result=spawnSync(python,[path.join(__dirname,'build-backend.py')],{cwd:root,stdio:'inherit',windowsHide:true});
if(result.error)throw new Error('The backend build Python could not start. Set VELLUM_BUILD_PYTHON to a prepared Windows backend environment.');
if(result.status!==0)process.exit(result.status || 1);
