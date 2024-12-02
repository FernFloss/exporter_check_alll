import asyncio
import json
from camera import Device
from prometheus_client import start_http_server

async def main():

    with open("config.json") as f:
        config = json.load(f)
    ffprobe_path = config.get("ffprobe_path")
    wstl_path = config.get("wstl_path")
    
    # Инициализация объектов Device
    devices = []
    for host in config.get("hosts", []):  # По умолчанию пустой список, если "hosts" нет
        device = Device(
            name=host.get("name", "Unnamed Device"),  # Имя устройства
            ip=host.get("ip"),                       # IP-адрес
            rtsp_urls=set(host.get("rtsp_url", [])), # RTSP URL как множество
            onvif_port=host.get("onvif_port", 80),   # Порт ONVIF
            onvif_username=host.get("onvif_username", ""),  # Имя пользователя ONVIF
            onvif_password=host.get("onvif_password", ""),  # Пароль ONVIF
        )
        devices.append(device)
    start_http_server(8000)
    while True:
        async with asyncio.TaskGroup() as tg:
            for device in devices:
                tg.create_task(device.check_all(wstl_path, ffprobe_path))
        await asyncio.sleep(60) #раз в минуту после опроса всех камер

if __name__ == "__main__":
    asyncio.run(main())