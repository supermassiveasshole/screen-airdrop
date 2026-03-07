FROM centos:7

RUN yum -y update && \
    yum -y install epel-release && \
    yum -y install python37 python37-pip gcc gcc-c++ make && \
    python3.7 -m pip install --upgrade pip && \
    python3.7 -m pip install pyinstaller

WORKDIR /work
COPY . /work

RUN python3.7 -m pip install . && \
    pyinstaller --onefile -n screen-airdrop-sender-legacy-centos7-x86_64 \
      -m screen_airdrop.sender.legacy
