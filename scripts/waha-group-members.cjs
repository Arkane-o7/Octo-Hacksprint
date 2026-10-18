// WAHA NOWEB 2026.9.2's legacy participants endpoint fetches EVERY group on
// every call. Use a fresh query for the requested group instead. No permission
// cache or stale membership fallback is introduced.
const fs = require('node:fs');

function patch(source) {
  const before = `    async getParticipants(id) {
        const groups = await this.sock.groupFetchAllParticipating();
        return groups[id].participants;
    }`;
  const after = `    async getParticipants(id) {
        const group = await this.sock.groupMetadata(id);
        return group.participants;
    }`;
  if (source.includes(after)) return source;
  if (source.split(before).length !== 2) {
    throw new Error('Unexpected WAHA participants implementation; review before upgrading.');
  }
  return source.replace(before, after);
}

if (require.main === module) {
  const path = process.argv[2] || '/app/dist/core/engines/noweb/session.noweb.core.js';
  fs.writeFileSync(path, patch(fs.readFileSync(path, 'utf8')));
}
module.exports = { patch };
