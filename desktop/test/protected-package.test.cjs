const {test} = require('node:test');
const assert = require('node:assert/strict');
const {signProtectedPackages} = require('../scripts/sign-protected-package.cjs');

test('Forge resolves the protected runtime version instead of the stock development version',async()=>{
  const config=require('../forge.config.cjs');
  const {getElectronVersion}=await import('../node_modules/@electron-forge/core-utils/dist/electron-version.js');
  const original={devDependencies:{electron:'44.9.0'}};
  const packaged=await config.hooks.readPackageJson(config,original);
  assert.equal(await getElectronVersion(process.cwd(),packaged),'44.5.1+wvcus');
  assert.equal(original.devDependencies.electron,'44.9.0');
});

test('packaging signs and verifies each output without interactive credential prompts',()=>{
  const calls=[];
  signProtectedPackages({platform:'win32',outputPaths:['output-a','output-b']},{python:'publisher-python',run:(...args)=>calls.push(args)});
  assert.equal(calls.length,4);
  assert.deepEqual(calls.map(call=>call[1].slice(2)),[
    ['--no-ask','sign-pkg','output-a'],['--no-ask','verify-pkg','output-a'],
    ['--no-ask','sign-pkg','output-b'],['--no-ask','verify-pkg','output-b']]);
});

test('a failed signing or verification prevents release success',()=>{
  for(const failure of [0,1]) {
    let count=0;
    assert.throws(()=>signProtectedPackages({platform:'win32',outputPaths:['output']},{run:()=>{if(count++===failure)throw Error('certificate unavailable');}}),/signing\/verification failed/);
  }
});
