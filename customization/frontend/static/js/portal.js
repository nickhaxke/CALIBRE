'use strict';
const dialog=document.getElementById('login-modal');let authenticated=false;
function getSafeRedirectUrl(){
  const p=new URLSearchParams(location.search);
  const next=p.get('next');
  if(next&&next.startsWith('/')&&!next.startsWith('//')&&!next.startsWith('/\\')){
    if(next.startsWith('/calibre')||next.startsWith('/reader')||next.startsWith('/admin')){
      return next;
    }
  }
  return '/calibre/institutional';
}
function accessLibrary(){if(authenticated){location.assign(getSafeRedirectUrl());return;}dialog.showModal();document.getElementById('login-username').focus();}
document.getElementById('top-access').onclick=accessLibrary;document.getElementById('hero-access').onclick=accessLibrary;document.getElementById('close-login').onclick=()=>dialog.close();dialog.addEventListener('click',e=>{if(e.target===dialog)dialog.close();});
document.getElementById('login-form').onsubmit=async event=>{event.preventDefault();const error=document.getElementById('login-error');const submit=document.getElementById('login-submit');error.hidden=true;submit.disabled=true;try{const username=document.getElementById('login-username').value.trim();const password=document.getElementById('login-password').value;if(!username||!password)throw Error('Please enter both your username and password.');const response=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})});const data=await response.json();if(!response.ok||!data.success)throw Error(data.error||'Sign in failed. Please try again.');document.getElementById('login-password').value='';location.assign(getSafeRedirectUrl());}catch(e){error.textContent=e.message;error.hidden=false;}finally{submit.disabled=false;}};
fetch('/api/auth/status',{cache:'no-store'}).then(r=>r.json()).then(data=>{authenticated=data.authenticated;if(authenticated){document.getElementById('session-name').textContent=data.user.displayName;document.getElementById('top-access').textContent='Enter library ↗';if(data.user&&data.user.role==='Administrator'){let adminBtn=document.getElementById('top-admin');if(!adminBtn){adminBtn=document.createElement('a');adminBtn.id='top-admin';adminBtn.href='/admin';adminBtn.className='outline';adminBtn.style.borderColor='#c5a059';adminBtn.style.color='#c5a059';adminBtn.style.marginRight='8px';adminBtn.textContent='Admin Console 🛡';document.getElementById('top-access').parentNode.insertBefore(adminBtn,document.getElementById('top-access'));}}}}).catch(()=>{});
const params=new URLSearchParams(location.search);if(params.has('login_required')){document.getElementById('login-message').textContent='Please sign in to continue.';dialog.showModal();}if(params.has('logged_out')){document.getElementById('session-name').textContent='You have signed out';history.replaceState({},'',location.pathname);}
