##Miflora-mqtt-daemon  Docker image
#Builds compact image to run as an alternative to installing the modules/service.  
ARG BLUEZ_VERSION=5.66
# The build image
FROM python:3.10.7-slim as builder
LABEL stage=builder
RUN apt-get update && apt-get install python3-docutils gcc libglib2.0-dev build-essential wget\
    libdbus-1-dev libudev-dev libical-dev libreadline-dev udev checkinstall -y && apt-get clean

# build bluez
RUN mkdir /bluezbuild
WORKDIR /bluezbuild
RUN wget http://www.kernel.org/pub/linux/bluetooth/bluez-${BLUEZ_VERSION}.tar.xz
# todo: check configure, we may not need systemd
RUN tar xvf bluez-${BLUEZ_VERSION}.tar.xz && cd bluez-${BLUEZ_VERSION} && \
    ./configure --prefix=/usr --mandir=/usr/share/man --sysconfdir=/etc --localstatedir=/var --enable-experimental --disable-systemd &&\
    make -j4
# needed by checkinstall
RUN mkdir /usr/lib/cups
# we use checkinstall to create a .deb package for bluez
RUN cd bluez-${BLUEZ_VERSION} && checkinstall --install=no --pkgname=bluez --pkgversion=${BLUEZ_VERSION} --pkgrelease=1 --pkglicense=GPL --pkggroup=bluetooth --pkgsource=http://www.kernel.org/pub/linux/bluetooth/bluez-${BLUEZ_VERSION}.tar.xz

COPY requirements.txt /app/requirements.txt
WORKDIR /app/
RUN pip install --user -r requirements.txt
COPY . /app

# The production image
FROM python:3.10.7-slim as app
# install bluez dependencies
RUN apt-get update && apt-get upgrade -y &&\
    apt-get install libglib2.0-0 libdbus-1-3 -y &&\ 
    apt-get clean
# copy compiled bluez and install it
COPY --from=builder /bluezbuild/bluez-${BLUEZ_VERSION}/*.deb /bluez-${BLUEZ_VERSION}/
RUN cd /bluez-${BLUEZ_VERSION} && dpkg -i *.deb && rm -rf /bluez-${BLUEZ_VERSION}
# enable bluetooth
RUN  echo 'export BLUETOOTH_ENABLED=1' | tee /etc/default/bluetooth

# Copy the application and python dependencies
COPY --from=builder /root/.local /root/.local
COPY --from=builder /app/miflora_mqtt_daemon/ /app/miflora_mqtt_daemon/
WORKDIR /app/
ENV PATH=/root/.local/bin:$PATH
CMD [ "python3", "-m","miflora_mqtt_daemon", "--config_dir", "/config" ]