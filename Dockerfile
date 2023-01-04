##Miflora-mqtt-daemon  Docker image
#Builds compact image to run as an alternative to installing the modules/service.  

# The build image
FROM python:3.10.7-slim as builder
LABEL stage=builder
RUN apt-get update && apt-get install python3-docutils gcc libglib2.0-dev build-essential \
                                      libdbus-1-dev libudev-dev libical-dev libreadline-dev \
                                      -y && apt-get clean

# build bluez 5.66
RUN wget http://www.kernel.org/pub/linux/bluetooth/bluez-5.66.tar.xz
RUN tar xvf bluez-5.66.tar.xz && cd bluez-5.66 && \
    ./configure --prefix=/usr --mandir=/usr/share/man --sysconfdir=/etc --localstatedir=/var --enable-experimental \
    make -j4 && make install

COPY requirements.txt /app/requirements.txt
WORKDIR /app/
RUN pip install --user -r requirements.txt
COPY . /app

# The production image
FROM python:3.10.7-slim as app
RUN apt-get update && apt-get install bluetooth bluez -y && apt-get clean
COPY --from=builder /root/.local /root/.local
COPY --from=builder /app/miflora-mqtt-daemon.py /app/miflora-mqtt-daemon.py
WORKDIR /app/
ENV PATH=/root/.local/bin:$PATH

CMD [ "python3", "./miflora-mqtt-daemon.py", "--config_dir", "/config" ]