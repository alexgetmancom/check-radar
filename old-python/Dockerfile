FROM python:3.11-slim

# Настройка временной зоны (для корректной работы планировщика отчетов по МСК)
ENV TZ=Europe/Moscow
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код (лишнее отсекается через .dockerignore)
COPY . .

# Создаем папку под БД
RUN mkdir -p data

# Запускаем main.py в unbuffered режиме
CMD ["python", "-u", "main.py"]
