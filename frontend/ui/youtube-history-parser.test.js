import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {expect, test} from 'vitest';

const source = readFileSync(resolve('../backend/agent/mcp/youtube_history.py'), 'utf8');
const script = source.match(/HISTORY_DOM = r"""([\s\S]*?)"""/)[1];
function extract(html) {
  document.body.innerHTML = html;
  window.ytcfg = {get:key=>key === 'LOGGED_IN' ? true : key === 'DATASYNC_ID' ? 'fixture-identity' : ''};
  return Function('window','document','location', 'return (' + script + ')()')(window,document,new URL('https://www.youtube.com/feed/history'));
}

test('modern history layout reads the plain-text creator and excludes recommendations', ()=> {
  const result = extract(`<ytd-item-section-renderer><div id="header">Yesterday</div>
    <yt-lockup-view-model><h3><a href="/watch?v=abcdefghijk">Real history video</a></h3>
      <yt-content-metadata-view-model><div class="ytContentMetadataViewModelMetadataRow">
        <span class="ytContentMetadataViewModelMetadataText">Observed creator</span>
        <span class="ytContentMetadataViewModelMetadataText">1.6M</span>
      </div></yt-content-metadata-view-model></yt-lockup-view-model></ytd-item-section-renderer>
    <yt-lockup-view-model><h3><a href="/watch?v=01234567890">Public recommendation</a></h3></yt-lockup-view-model>`);
  expect(result.items).toHaveLength(1);
  expect(result.items[0]).toMatchObject({title:'Real history video',channel_title:'Observed creator',day_label:'Yesterday'});
});

test('classic history layout retains official channel identity', ()=> {
  const result = extract(`<ytd-item-section-renderer><div id="header">Today</div><ytd-video-renderer>
    <a id="video-title" href="/watch?v=abcdefghijk">Watched video</a>
    <div id="channel-name"><a href="/channel/UC-fixture">Actual channel</a></div>
    </ytd-video-renderer></ytd-item-section-renderer>`);
  expect(result.items[0]).toMatchObject({channel_title:'Actual channel',channel_id:'UC-fixture',day_label:'Today'});
});
