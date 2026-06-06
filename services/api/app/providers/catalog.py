from ..models import BgmTrack, VoiceProfile


BUILT_IN_VOICES = [
    VoiceProfile(
        voice_id="classic-female",
        name="经典女声",
        description="适合日常口播、种草、生活方式内容",
    ),
    VoiceProfile(
        voice_id="classic-male",
        name="经典男声",
        description="适合知识口播、测评、商业讲解",
    ),
    VoiceProfile(
        voice_id="warm-narrator",
        name="温暖旁白",
        description="适合情绪价值、故事叙述、品牌表达",
    ),
    VoiceProfile(
        voice_id="energetic-host",
        name="活力主播",
        description="适合带货、促销、节奏较快的视频",
    ),
]

BUILT_IN_BGM = [
    BgmTrack(bgm_id="default-light", name="轻快日常", mood="light"),
    BgmTrack(bgm_id="default-tech", name="科技律动", mood="tech"),
    BgmTrack(bgm_id="default-warm", name="温暖叙事", mood="warm"),
]
