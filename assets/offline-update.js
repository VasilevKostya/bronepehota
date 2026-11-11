// Resolve only after the browser has installed and verified the complete release.
// Activation remains an explicit action by the caller.
export function checkOfflineUpdate(registration,{timeoutMs=90000}={}){
  return new Promise((resolve,reject)=>{
    let worker,finished=false;
    const finish=(error,result)=>{
      if(finished)return;
      finished=true;clearTimeout(timer);
      worker?.removeEventListener('statechange',inspect);
      error?reject(error):resolve(result);
    };
    const inspect=()=>{
      if(worker.state==='redundant')finish(new Error('Offline installation failed'));
      else if(['installed','activating','activated'].includes(worker.state))finish(null,registration.waiting||null);
    };
    const watch=()=>{
      if(finished)return;
      worker=registration.installing||registration.waiting;
      if(!worker){finish(null,null);return;}
      worker.addEventListener('statechange',inspect);inspect();
    };
    const timer=setTimeout(()=>finish(new Error('Offline update timed out')),timeoutMs);
    if(registration.installing)watch();
    else Promise.resolve().then(()=>registration.update()).then(watch,error=>finish(error));
  });
}
