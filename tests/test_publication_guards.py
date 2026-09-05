import json
import subprocess
from pathlib import Path

import pytest

import weekly_update as W


@pytest.fixture
def repositories(tmp_path,monkeypatch):
    names=['correlations','earthquakes']
    remote_heads={}
    for name in names:
        root=tmp_path/name;root.mkdir()
        subprocess.run(['git','init','-b','main',str(root)],check=True,capture_output=True)
        for key,value in [('user.name','Biblejustin'),('user.email','275883147+Biblejustin@users.noreply.github.com'),('commit.gpgsign','false')]:
            subprocess.run(['git','-C',str(root),'config',key,value],check=True)
        (root/'source.py').write_text('original\n')
        subprocess.run(['git','-C',str(root),'add','source.py'],check=True)
        subprocess.run(['git','-C',str(root),'commit','-m','fixture'],check=True,capture_output=True)
        subprocess.run(['git','-C',str(root),'remote','add','origin',f'https://github.com/Biblejustin/{name}.git'],check=True)
        remote_heads[name]=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    monkeypatch.setattr(W,'ROOT',tmp_path);monkeypatch.setattr(W,'REPOS',names)
    original=subprocess.check_output
    def output(cmd,*args,**kwargs):
        if cmd==['gh','api','user']:return json.dumps({'login':'Biblejustin','id':275883147})
        if 'ls-remote' in cmd:
            return remote_heads[Path(cmd[2]).name]+'\trefs/heads/main\n'
        return original(cmd,*args,**kwargs)
    monkeypatch.setattr(W.subprocess,'check_output',output)
    account=W.verify_publish_targets()
    account['_test_remote_heads']=remote_heads
    return tmp_path,account


def test_status_sidecar_is_published_and_arbitrary_json_is_not(repositories):
    root,account=repositories
    path=root/'earthquakes/quakes.sqlite.significant.status.json';path.write_text('{}')
    assert W.publication_paths('earthquakes',account)==[path.name]
    (root/'earthquakes/settings.json').write_text('{}')
    with pytest.raises(RuntimeError,match='unexpected source'):W.publication_paths('earthquakes',account)


def test_status_sidecar_committed_and_no_dirty_file_blocks_next_run(repositories,monkeypatch):
    root,account=repositories
    path=root/'earthquakes/quakes.sqlite.significant.status.json';path.write_text('{}')
    original=subprocess.run;pushes=[]
    def run(cmd,*args,**kwargs):
        if 'push' in cmd:
            pushes.append(cmd)
            account['_test_remote_heads'][Path(cmd[2]).name]=W.git(Path(cmd[2]).name,'rev-parse','HEAD')
            return subprocess.CompletedProcess(cmd,0)
        return original(cmd,*args,**kwargs)
    monkeypatch.setattr(W.subprocess,'run',run)
    W.publish(account)
    assert not W.git('earthquakes','status','--porcelain')
    assert W.git('earthquakes','show','HEAD:'+path.name)=='{}'
    assert len(pushes)==1 and pushes[0][-2:]==['https://github.com/Biblejustin/earthquakes.git','HEAD:refs/heads/main']
    W.verify_publish_targets()


@pytest.mark.parametrize('staged',[False,True])
def test_source_edit_in_later_repo_stops_before_any_output_commit(repositories,staged):
    root,account=repositories
    (root/'correlations/data').mkdir();(root/'correlations/data/new.csv').write_text('value\n1\n')
    (root/'earthquakes/source.py').write_text('concurrent edit\n')
    if staged:subprocess.run(['git','-C',str(root/'earthquakes'),'add','source.py'],check=True)
    with pytest.raises(RuntimeError,match='unexpected source'):W.publish(account)
    assert W.git('correlations','rev-parse','HEAD')==account['verified_repositories']['correlations']['head']
    assert not W.git('correlations','diff','--cached','--name-only')


@pytest.mark.parametrize('change',['branch','commit'])
def test_changed_git_state_stops_publication(repositories,change):
    root,account=repositories
    if change=='branch':subprocess.run(['git','-C',str(root/'earthquakes'),'switch','-c','concurrent-work'],check=True,capture_output=True)
    else:subprocess.run(['git','-C',str(root/'earthquakes'),'commit','--allow-empty','-m','concurrent commit'],check=True,capture_output=True)
    with pytest.raises(RuntimeError,match='branch or commit changed'):W.publication_paths('earthquakes',account)


def test_missing_initial_verification_cannot_publish(repositories):
    with pytest.raises(RuntimeError,match='missing initial'):W.publication_paths('earthquakes',{'login':'Biblejustin','id':275883147})


def test_source_rename_into_generated_directory_stops_batch(repositories):
    root,account=repositories
    (root/'correlations/data').mkdir();(root/'correlations/data/new.csv').write_text('value\n1\n')
    (root/'earthquakes/data').mkdir()
    subprocess.run(['git','-C',str(root/'earthquakes'),'mv','source.py','data/source.py'],check=True)
    with pytest.raises(RuntimeError,match='unexpected source'):W.publish(account)
    assert W.git('correlations','rev-parse','HEAD')==account['verified_repositories']['correlations']['head']
    assert not W.git('correlations','diff','--cached','--name-only')


@pytest.mark.parametrize('setting',['url','pushurl'])
def test_changed_later_remote_stops_batch_before_commit(repositories,setting):
    root,account=repositories
    (root/'correlations/data').mkdir();(root/'correlations/data/new.csv').write_text('value\n1\n')
    subprocess.run(['git','-C',str(root/'earthquakes'),'config',f'remote.origin.{setting}','https://example.invalid/earthquakes.git'],check=True)
    with pytest.raises(RuntimeError,match='Unexpected remote|Every push target'):W.publish(account)
    assert W.git('correlations','rev-parse','HEAD')==account['verified_repositories']['correlations']['head']
    assert not W.git('correlations','diff','--cached','--name-only')


def test_unpublished_source_commit_stops_initial_verification(repositories):
    root,account=repositories
    (root/'earthquakes/source.py').write_text('unpublished source edit\n')
    subprocess.run(['git','-C',str(root/'earthquakes'),'add','source.py'],check=True)
    subprocess.run(['git','-C',str(root/'earthquakes'),'commit','-m','unpublished edit'],check=True,capture_output=True)
    with pytest.raises(RuntimeError,match='local and remote branch differ'):W.verify_publish_targets()


def test_remote_advanced_during_refresh_stops_before_any_commit(repositories):
    root,account=repositories
    (root/'correlations/data').mkdir();(root/'correlations/data/new.csv').write_text('value\n1\n')
    account['_test_remote_heads']['earthquakes']='0'*40
    with pytest.raises(RuntimeError,match='local and remote branch differ'):W.publish(account)
    assert W.git('correlations','rev-parse','HEAD')==account['verified_repositories']['correlations']['head']
    assert not W.git('correlations','diff','--cached','--name-only')
