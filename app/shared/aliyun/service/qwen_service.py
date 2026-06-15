from canary_framework import service, before_startup
from canary_framework.core.service import ServiceBase
from openai import OpenAI


@service()
class QwenService(ServiceBase):

    def __init__(self):
        super().__init__()
        self.client = None

    @before_startup
    def after_init(self):
        self.client = OpenAI(
            api_key=self.config.DASHSCOPE_API_KEY,
            base_url=self.config.DASHSCOPE_API_BASE
        )

    def vl(self, video_url):
        try:
            completion = self.client.chat.completions.create(
                model="qwen3.7-plus",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            # 直接传入视频文件时，请将type的值设置为video_url
                            {
                                "type": "video_url",
                                "video_url": {
                                    "url": video_url
                                },
                                "fps": 2
                            },
                            {
                                "type": "text",
                                "text": "这段视频的内容是什么?"
                            }
                        ]
                    }
                ]
            )

            return completion.choices[0].message.content
        except Exception as e:
            return ""

    def ocr(self, image_url):
        try:
            completion = self.client.chat.completions.create(
                model="qwen-vl-ocr-latest",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": image_url},
                                # 输入图像的最小像素阈值，小于该值图像会放大，直到总像素大于min_pixels
                                "min_pixels": 32 * 32 * 3,
                                # 输入图像的最大像素阈值，超过该值图像会缩小，直到总像素低于max_pixels
                                "max_pixels": 32 * 32 * 8192
                            },
                            # 模型支持在以下text字段中传入Prompt，若未传入，则会使用默认的Prompt：Please output only the text content from the image without any additional descriptions or formatting.
                            {
                                "type": "text",
                                "text": self.config.QWEN_OCR_SYSTEM_PROMPT
                            }
                        ]
                    }
                ])
            return completion.choices[0].message.content
        except Exception as e:
            return ""

    def asr(self, audio_url):
        try:
            stream_enabled = False  # 是否开启流式输出
            completion = self.client.chat.completions.create(
                model="qwen3-asr-flash",
                messages=[
                    {
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {
                                    "data": audio_url
                                }
                            }
                        ],
                        "role": "user"
                    }
                ],
                stream=stream_enabled,
                # stream设为False时，不能设置stream_options参数
                # stream_options={"include_usage": True},
                extra_body={
                    "asr_options": {
                        # "language": "zh",
                        "enable_itn": False
                    }
                }
            )
            if stream_enabled:
                full_content = ""
                print("流式输出内容为：")
                for chunk in completion:
                    # 如果stream_options.include_usage为True，则最后一个chunk的choices字段为空列表，需要跳过（可以通过chunk.usage获取 Token 使用量）
                    print(chunk)
                    if chunk.choices and chunk.choices[0].delta.content:
                        full_content += chunk.choices[0].delta.content
                return full_content
            else:
                return completion.choices[0].message.content
        except Exception as e:
            return ""
