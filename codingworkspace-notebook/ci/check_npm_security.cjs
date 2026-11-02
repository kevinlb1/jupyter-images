// Exercise the fixed bundled modules and their real dependency closure.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createRequire } = require('node:module');
const npmRoot = process.argv[2] || '/usr/local/lib/node_modules/npm';
const npmRequire = createRequire(path.join(npmRoot, 'package.json'));
const semver = npmRequire('semver');
function metadata(requireFrom, name) {
  let current = path.dirname(requireFrom.resolve(name));
  while (true) {
    const filename = path.join(current, 'package.json');
    if (fs.existsSync(filename)) {
      const value = JSON.parse(fs.readFileSync(filename, 'utf8'));
      if (value.name === name) return { value, filename };
    }
    const parent = path.dirname(current);
    assert.notEqual(parent, current, `Cannot identify ${name}`);
    current = parent;
  }
}
for (const [name, version] of Object.entries({glob:'14.0.2',minimatch:'11.0.1',
    'path-scurry':'3.0.0','@isaacs/nonrecursive-glob-match':'1.0.1'})) {
  const { value, filename } = metadata(npmRequire, name);
  assert.equal(value.version, version);
  const dependencyRequire = createRequire(filename);
  for (const [dependency, range] of Object.entries(value.dependencies || {})) {
    assert(semver.satisfies(metadata(dependencyRequire, dependency).value.version, range),
      `${name}: incompatible dependency ${dependency} ${range}`);
  }
}
const { minimatch } = npmRequire('minimatch');
assert(minimatch('src/app.js', '**/*.js'));
assert(minimatch('one.js', '{one,two}.js'));
assert(!minimatch('src/app.py', '**/*.js'));
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'cw-npm-security-'));
(async () => {
  try {
    fs.mkdirSync(path.join(root, 'src'));
    fs.writeFileSync(path.join(root, 'src/app.js'), 'fixture');
    fs.writeFileSync(path.join(root, 'src/app.py'), 'fixture');
    const { glob, globSync } = npmRequire('glob');
    assert.deepEqual(globSync('**/*.js', { cwd:root }), ['src/app.js']);
    assert.deepEqual(await glob('**/*.js', { cwd:root }), ['src/app.js']);
    const controller = new AbortController();
    controller.abort();
    await assert.rejects(glob('**/*', { cwd:root, signal:controller.signal }), { name:'AbortError' });
    console.log('Fixed npm glob/minimatch dependency closure and operations passed');
  } finally {
    fs.rmSync(root, { recursive:true, force:true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
