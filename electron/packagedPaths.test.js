const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { buildBackendLaunch } = require('./backendManager');
const { buildDiagnosticLaunch, getSupportPaths } = require('./supportTools');

test('packaged demo preserves mode and diagnostics share writable data', () => {
  const options = { appPath: 'source', resourcesPath: 'resources', userDataPath: 'User Space 한글', isPackaged: true, mode: 'demo', port: 49123 };
  assert.deepEqual(buildBackendLaunch(options).args, ['--demo', '--port', '49123']);
  assert.equal(buildDiagnosticLaunch(options).options.env.TFT_COACH_USER_DATA, options.userDataPath);
  assert.equal(getSupportPaths(options).metadataFiles[0], path.join('resources', 'assets', 'models', 'unit_classifier.json'));
});
