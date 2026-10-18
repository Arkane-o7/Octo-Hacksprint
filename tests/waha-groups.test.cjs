const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { patch } = require('../scripts/waha-group-members.cjs');

const original = `class Session {
    async getParticipants(id) {
        const groups = await this.sock.groupFetchAllParticipating();
        return groups[id].participants;
    }
}`;

test('participants query only the requested group and observe membership changes', async () => {
  const Session = vm.runInNewContext(patch(original) + '; Session');
  const session = new Session();
  let members = [{ id: 'member@lid', phoneNumber: '123@c.us' }];
  const requested = [];
  session.sock = {
    groupFetchAllParticipating() { throw new Error('Must not fetch all groups'); },
    async groupMetadata(id) { requested.push(id); return { participants: members }; },
  };
  assert.equal(await session.getParticipants('school@g.us'), members);
  members = [];
  assert.equal(await session.getParticipants('school@g.us'), members);
  assert.deepEqual(requested, ['school@g.us', 'school@g.us']);
  session.sock.groupMetadata = async () => { throw new Error('offline'); };
  await assert.rejects(session.getParticipants('school@g.us'), /offline/);
});

test('patch is idempotent and rejects unexpected upstream code', () => {
  assert.equal(patch(patch(original)), patch(original));
  assert.throws(() => patch('changed upstream implementation'), /Unexpected WAHA/);
  assert.throws(() => patch(original + original), /Unexpected WAHA/);
});
