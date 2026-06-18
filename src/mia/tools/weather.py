"""
Weather 工具 — 使用 wttr.in 免费 API 查询天气

wttr.in 是一个免费的天气查询服务，无需 API Key。
返回指定城市的天气信息（温度、天气状况、湿度、风速等）。
"""

from typing import Optional

import httpx
from loguru import logger

from mia.tools.base import Tool, ToolResult


class WeatherTool(Tool):
    """天气查询工具 — wttr.in"""

    name = "weather"
    description = (
        "查询指定城市的天气信息，支持今天和未来几天的天气预报。"
        "返回: 温度（最高/最低）、天气状况、湿度、风速、风向等。"
        "适用于: 天气查询、出行建议。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "城市名称（中文或英文），如 '嘉兴'、'Beijing'、'上海'",
            },
            "days": {
                "type": "integer",
                "description": "查询天数 (1-3, 默认2。1=仅今天, 2=今天+明天, 3=今天+明天+后天)",
            },
        },
        "required": ["city"],
    }

    # wttr.in 天气代码 → 中文描述映射
    WEATHER_CODES: dict[str, str] = {
        "113": "晴天", "116": "晴间多云",
        "119": "多云", "122": "阴天",
        "143": "雾", "176": "阵雨",
        "179": "小雪", "182": "雨夹雪",
        "185": "冻雨", "200": "雷阵雨",
        "227": "暴风雪", "230": "暴风雪",
        "248": "雾", "260": "大雾",
        "263": "小雨", "266": "小雨",
        "281": "冻雨", "284": "冻雨",
        "293": "小雨", "296": "小雨",
        "299": "中雨", "302": "中雨",
        "305": "大雨", "308": "暴雨",
        "311": "小雨夹雪", "314": "中雨夹雪",
        "317": "大雨夹雪", "320": "雨夹雪",
        "323": "小雪", "326": "小雪",
        "329": "中雪", "332": "中雪",
        "335": "大雪", "338": "大雪",
        "350": "冰雹", "353": "阵雨",
        "356": "中雨", "359": "暴雨",
        "362": "小雪", "365": "中雪",
        "368": "大雪", "371": "大雪",
        "374": "冰雹", "377": "冰雹",
        "386": "雷阵雨", "389": "雷暴",
        "392": "雷暴雪", "395": "大雪",
    }

    def _translate_weather_code(self, code: str) -> str:
        """将 wttr.in 天气代码转为中文描述"""
        return self.WEATHER_CODES.get(code, f"未知({code})")

    def _format_weather(self, data: dict, city: str, days: int) -> str:
        """
        将 wttr.in JSON 响应格式化为可读文本

        wttr.in JSON 结构:
        {
          "weather": [
            {
              "date": "2026-06-18",
              "astronomy": [{"sunrise": "...", "sunset": "..."}],
              "mintempC": "22", "maxtempC": "31",
              "hourly": [
                {
                  "time": "0", "tempC": "25", "humidity": "80",
                  "weatherCode": "116", "windSpeedKmph": "15",
                  "winddir16Point": "SE", "weatherDesc": [...],
                  "chanceofrain": "10",
                },
                ...
              ]
            },
            ...
          ]
        }
        """
        weather_list = data.get("weather", [])
        if not weather_list:
            return f"未获取到 {city} 的天气数据。"

        # 限制天数
        weather_list = weather_list[:days]

        lines = [f"📍 {city} 天气预报", "=" * 40]

        for day_data in weather_list:
            date = day_data.get("date", "未知日期")
            mintemp = day_data.get("mintempC", "?")
            maxtemp = day_data.get("maxtempC", "?")
            astronomy = day_data.get("astronomy", [{}])[0] if day_data.get("astronomy") else {}
            sunrise = astronomy.get("sunrise", "?")
            sunset = astronomy.get("sunset", "?")

            lines.append(f"\n📅 {date}")
            lines.append(f"   温度: {mintemp}°C ~ {maxtemp}°C")
            lines.append(f"   日出: {sunrise} | 日落: {sunset}")

            # 从 hourly 数据中提取代表性信息
            hourly = day_data.get("hourly", [])
            if hourly:
                # 取白天时段 (8:00-20:00) 的平均值
                daytime_hours = []
                for h in hourly:
                    try:
                        hour_num = int(h.get("time", "0").zfill(3)[:2])
                    except ValueError:
                        hour_num = 0
                    if 6 <= hour_num <= 20:
                        daytime_hours.append(h)

                # 如果没有白天数据，用全部
                if not daytime_hours:
                    daytime_hours = hourly

                # 统计天气状况（取最常见的）
                from collections import Counter
                weather_codes = [
                    h.get("weatherCode", "") for h in daytime_hours
                ]
                if weather_codes:
                    most_common_code = Counter(weather_codes).most_common(1)[0][0]
                    weather_desc = self._translate_weather_code(most_common_code)
                    lines.append(f"   天气: {weather_desc}")

                # 平均湿度
                humidities = [
                    int(h.get("humidity", 0))
                    for h in daytime_hours if h.get("humidity")
                ]
                if humidities:
                    avg_humidity = sum(humidities) // len(humidities)
                    lines.append(f"   湿度: ~{avg_humidity}%")

                # 风速
                wind_speeds = [
                    int(h.get("windspeedKmph", 0))
                    for h in daytime_hours if h.get("windspeedKmph")
                ]
                if wind_speeds:
                    avg_wind = sum(wind_speeds) // len(wind_speeds)
                    wind_dirs = [
                        h.get("winddir16Point", "")
                        for h in daytime_hours if h.get("winddir16Point")
                    ]
                    most_common_dir = Counter(wind_dirs).most_common(1)[0][0] if wind_dirs else "?"
                    lines.append(f"   风速: ~{avg_wind} km/h ({most_common_dir})")

                # 降雨概率
                rain_chances = [
                    int(h.get("chanceofrain", 0))
                    for h in daytime_hours if h.get("chanceofrain")
                ]
                if rain_chances:
                    max_rain = max(rain_chances)
                    lines.append(f"   降雨概率: 最高 {max_rain}%")

        lines.append(f"\n数据来源: wttr.in")
        return "\n".join(lines)

    async def execute(
        self,
        city: str,
        days: int = 2,
    ) -> ToolResult:
        """
        查询天气

        Args:
            city: 城市名称
            days: 查询天数 (1-3)

        Returns:
            ToolResult
        """
        days = max(1, min(days, 3))  # 限制 1-3 天

        logger.info("[WeatherTool] 查询天气: city={}, days={}", city, days)

        try:
            # wttr.in API — 免费、无需 API Key
            # format=j1 返回 JSON 格式
            url = f"https://wttr.in/{city}"
            params = {
                "format": "j1",
                "lang": "zh",
            }

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()

            if not data or "weather" not in data:
                return ToolResult(
                    success=False,
                    error=f"未找到城市 '{city}' 的天气数据，请检查城市名称是否正确。",
                )

            formatted = self._format_weather(data, city, days)
            return ToolResult(success=True, data=formatted)

        except httpx.HTTPStatusError as e:
            logger.error("[WeatherTool] HTTP 错误: {}", e)
            return ToolResult(
                success=False,
                error=f"天气查询 HTTP 错误 ({e.response.status_code})，请稍后重试。",
            )
        except httpx.TimeoutException:
            logger.error("[WeatherTool] 请求超时")
            return ToolResult(
                success=False,
                error="天气查询超时，请稍后重试。",
            )
        except Exception as e:
            logger.error("[WeatherTool] 查询失败: {}", e)
            return ToolResult(success=False, error=f"天气查询失败: {e}")
