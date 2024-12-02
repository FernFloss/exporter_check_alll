from typing import Self
from prometheus_client import Gauge
import subprocess
import asyncio
from onvif import ONVIFCamera
import re

# Возможные значения статусы: "Unknown" - 0(никто не ответил, вылетилии по таймауту), "Active" - 1, "Error" - -1
STATUS = {1: "Active", -1: "Error", 0: "Unknown"}
TIMEOUT = 5 

class Device:
    """Class devices"""

    def __init__(
        self,
        name: str,
        ip: str,
        rtsp_urls: set[str],
        onvif_port: int,
        onvif_username: str,
        onvif_password: str,
    ):
        """
        Инициализация объекта RTSPClass.

        :param name: строка, содержащая имя устройства
        :param ip:строка, содержащая IP-адрес камеры
        :param rtsp_url: множество, содержащее URL RTSP потока/ов
        :param onvif_port:строка, содержащая порт ONVIF
        :param onvif_username: строка, содержащая имя пользователя ONVIF
        :param onvif_password: строка, содержащая пароль ONVIF
        """
        self.name = name
        self.ip = ip
        self.rtsp_url = rtsp_urls
        self.onvif_port = onvif_port
        self.onvif_username = onvif_username
        self.onvif_password = onvif_password
        
         # Генерация валидного имени метрики
        metric_name = self._sanitize_metric_name(name)
        
        self.rtsp_label = Gauge(
            "Status_RTSP", name,["ip", "status", "error", "rtsp_url"]
        )
        self.onvif_label = Gauge(
           "Status_ONVIF", name, ["ip", "status", "error", "onvif_username"]
        )

        # Установка начальных значений метрик
        self.rtsp_label.labels(
            ip=self.ip,
            status=STATUS[0],
            error=None,
            rtsp_url=None ,
        ).set(0)

        self.onvif_label.labels(
            ip=self.ip, status=STATUS[0], error=None, onvif_username=self.onvif_username
        ).set(0)
        
        
    def _sanitize_metric_name(self, name: str) -> str:
        # Удаляет недопустимые символы и заменяет пробелы на подчеркивания
        name = name.lower()  # Преобразуем в нижний регистр
        name = re.sub(r'[^a-zA-Z0-9_]', '_', name)  # Заменяем всё, кроме допустимых символов
        return name    

    def set_status_onvif(self, status_nomber: int, error: str = None) -> None:
        self.onvif_label.clear()
        self.onvif_label.labels(
            ip=self.ip,
            status=STATUS[status_nomber],
            error=error,
            onvif_username=self.onvif_username,
        ).set(status_nomber)

    def set_status_rtsp(self, status_nomber: int, rtsp_url_to_status: str,error: str = None) -> None:
        #Очистка метрик будет происходить в ртсп чекере
        self.rtsp_label.labels(
            ip=self.ip,
            status=STATUS[status_nomber],
            error=error,
            rtsp_url=rtsp_url_to_status,
        ).set(status_nomber)

    async def check_onvif(self, path_wsdl:str) -> set[str]:
        try:
            # Создаём асинхронное подключение к камере
            camera = ONVIFCamera(self.ip, self.onvif_port, self.onvif_username, 
                                self.onvif_password, path_wsdl)
            await camera.update_xaddrs()
            device_camera = await camera.create_devicemgmt_service()
            await device_camera.GetDeviceInformation()
            
            #Проверили камеру, если все нормально проставили 1 по онфив
            self.set_status_onvif(1)
            
            # Получение RTSP URL через медиасервис ONVIF
            media_service = await camera.create_media_service()
            profiles = await media_service.GetProfiles()
            
            set_rtsp = (self.rtsp_url).copy()
            for profile in profiles:
                uri = await media_service.GetStreamUri(
                    {"StreamSetup": {"Stream": "RTP-Unicast", "Transport": "RTSP"}, "ProfileToken": profile.token}
                )
                set_rtsp.add(uri.Uri)
            await camera.close()
            return set_rtsp
        except Exception as e:
            error_message = str(e)
            if "All connection attempts failed" in error_message:
                self.set_status_onvif(0, error_message)
                return
            else:
                error_message = str(e)
                self.set_status_onvif(-1,error_message)
                return self.rtsp_url
            
    async def check_rtsps(self, rtsp_url: str, path_ffmpeg:str) -> None:
        ffmpeg_command = [path_ffmpeg, "-rtsp_transport", "tcp", "-i", rtsp_url ]     
        try:
            process = await asyncio.create_subprocess_exec(
                *ffmpeg_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=TIMEOUT)
            
                if process.returncode == 0:
                    # Процесс завершился успешно
                    self.set_status_rtsp(1, rtsp_url)
                    return 
                else:
                    # ffmpeg завершился с ошибкой
                    error_message = stderr.decode("utf-8")
                    self.set_status_rtsp(-1, rtsp_url, error_message)
                    return 
            except asyncio.TimeoutError:
                # Превышен таймаут
                process.kill()
                await process.wait()
                self.set_status_rtsp(0, rtsp_url, "Timeout")
                return False, 
        except Exception as e:
            self.set_status_rtsp(-1, rtsp_url, str(e))
            return 
        
    async def check_all(self, path_wsdl:str, path_ffmpeg:str) -> None:
        self.rtsp_label.clear()
        for i in (await self.check_onvif(path_wsdl)):
            await self.check_rtsps(i, path_ffmpeg)
        
            