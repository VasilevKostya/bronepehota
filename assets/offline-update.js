// Prefer an already verified waiting release, even when offline. Network and stalled
// installation deadlines are separate; useful progress extends only the latter.
export function checkOfflineUpdate(registration,{timeoutMs=30000,installTimeoutMs=120000,serviceWorker=globalThis.navigator?.serviceWorker,onProgress=()=>{}}={}){
  return new Promise((resolve,reject)=>{
    let worker,finished=false,timer,lastCompleted=-1,lastTransferred=0,failureReason;
    const arm=ms=>{clearTimeout(timer);timer=setTimeout(()=>finish(new Error('Offline update timed out')),ms);};
    const finish=(error,result)=>{
      if(finished)return;
      finished=true;clearTimeout(timer);
      worker?.removeEventListener('statechange',inspect);
      serviceWorker?.removeEventListener('message',message);
      error?reject(error):resolve(result);
    };
    const message=event=>{
      const data=event.data;
      if(event.source!==worker||data?.type!=='OFFLINE_PROGRESS')return;
      if(data.completed>lastCompleted||data.transferredBytes>lastTransferred){lastCompleted=data.completed;lastTransferred=data.transferredBytes||0;arm(installTimeoutMs);}
      if(data.phase==='failed')failureReason=data.reason;
      onProgress(data);
    };
    const inspect=()=>{
      if(worker.state==='redundant')finish(Object.assign(new Error('Offline installation failed'),{code:failureReason}));
      else if(['installed','activating','activated'].includes(worker.state))finish(null,registration.waiting||null);
    };
    const watch=()=>{
      if(finished)return;
      worker=registration.waiting||registration.installing;
      if(!worker){finish(null,null);return;}
      arm(installTimeoutMs);
      worker.addEventListener('statechange',inspect);
      serviceWorker?.addEventListener('message',message);
      worker.postMessage?.({type:'STATUS'});
      inspect();
    };
    arm(timeoutMs);
    if(registration.waiting||registration.installing)watch();
    else Promise.resolve().then(()=>registration.update()).then(watch,error=>finish(error));
  });
}

export function activateOfflineUpdate(worker,serviceWorker,{timeoutMs=15000}={}){
  return new Promise((resolve,reject)=>{
    let timer;
    const finish=error=>{
      clearTimeout(timer);
      serviceWorker.removeEventListener('controllerchange',changed);
      worker.removeEventListener('statechange',inspect);
      error?reject(error):resolve();
    };
    const changed=()=>{if(serviceWorker.controller===worker)finish();};
    const inspect=()=>{if(worker.state==='redundant')finish(new Error('Offline activation failed'));};
    serviceWorker.addEventListener('controllerchange',changed);
    worker.addEventListener('statechange',inspect);
    timer=setTimeout(()=>finish(new Error('Offline activation timed out')),timeoutMs);
    try{worker.postMessage({type:'ACTIVATE'});}catch(error){finish(error);}
  });
}

export function offlineProgressText(data,hasSavedCopy){
  if(data.phase==='checking')return 'Проверяем обновления…';
  if(data.phase==='ready')return hasSavedCopy?'Обновление готово.':'Материалы сохранены.';
  if(data.phase==='failed')return data.reason==='storage'?'Недостаточно места для обновления. Освободите место на устройстве и повторите.':hasSavedCopy?'Загрузка прервана. Сохранённая копия доступна. Нажмите, чтобы продолжить.':'Не удалось сохранить. Нажмите, чтобы продолжить загрузку.';
  const total=data.totalBytes||data.total,done=data.totalBytes?data.completedBytes+(data.receivingBytes||0):data.completed;
  const percent=total?Math.min(100,Math.floor(100*done/total)):0;
  return (hasSavedCopy?'Загружаем изменения: ':'Сохраняем для чтения без интернета: ')+percent+'%.';
}
