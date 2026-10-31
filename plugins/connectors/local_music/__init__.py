"""Hermes-compatible Local Music plugin, backed by the canonical music library."""


def register(ctx):
    ctx.register_connector(id='local_music',name='Local Music',category='Media & Entertainment',
        capabilities=['local_music.library','local_music.playback'],status_factory=lambda:{
            'id':'local_music','configured':True,'status':'ready',
            'notes':'Open Music → Local to import audio files, save playlist information, and match missing songs to files you own.'})
