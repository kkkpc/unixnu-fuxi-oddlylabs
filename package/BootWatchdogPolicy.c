// SPDX-License-Identifier: MIT
// Port of UniXNU-sheng package/BootWatchdogPolicy.c (sha256
// 243ba6430c6a095fa986bc01d6237ef5811d71ca40a122cacf6421a0289aac31), the
// definition of sheng_boot_watchdog_policy that
// patches/xnu-12377/zzz-boot-progress.patch calls from load_init_program
// when XNU_OWNER_DATA_MOUNT and XNU_BOOT_PROGRESS are both on. The fuxi
// line had no counterpart until the Data stage flipped DATA_MOUNT on
// (Build #51 linked nothing else: exactly one undefined symbol).
// One deliberate omission: sheng's PE_builtin_boot_args[] is NOT ported.
// It is that board's always-on switches, and it would take effect on
// every boot - including sheng-disable-jobs=com.apple.cameracaptured, which
// would make this policy write a disabled.plist for the camera daemon.
// Fuxi's kernel arguments live in board.toml [payload] and none of the
// sheng-* switches is set there, so with this port the policy reads the
// loader's command line, finds nothing configured and returns 0.
// A future step that wants job disabling on fuxi should add its own
// switches to board.toml, not revive sheng's builtin line.
// Explicit temporary bring-up policy for an unavailable watchdog backend.
// Runs after writable scratch Data mounts, before the unchanged launchd exec.
// One fuxi addition beyond sheng's policy: sheng-skip-setup=1 writes the official
// 21H461 skip-setup preference profile into the mounted Data volume from the
// kernel (see sheng_boot_skip_setup below). The host-side seed tool cannot do
// this here: fuxi's Data is a persistent store, not a seed the host can edit.
#include <sys/param.h>
#include <sys/systm.h>
#include <sys/proc.h>
#include <sys/sysproto.h>
#include <sys/fcntl.h>
#include <sys/stat.h>
#include <pexpert/pexpert.h>

static const char policy_head[] =
 "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
 "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
 "<plist version=\"1.0\"><dict>";
static const char policy_watchdogd[]="<key>com.apple.watchdogd</key><true/>";
// Bring-up isolation: hardware stacks show identityservicesd, contextstored and locationd in a
// cycle of synchronous XPC waits. A disabled job makes its Mach service lookups fail instead of hang.
// sheng-disable-jobs=<label>[,<label>...] (restricted label characters, bounded length).
static const char policy_tail[]="</dict></plist>\n";
// sheng-lite=1: jobs that only reach for the network, iCloud or the photo library and have nothing to do on this tablet (no radios, no accounts),
// all of which start at the first boot of a fresh Data and compete with SpringBoard for the CPU and for memory. The first four are the
// cycle of synchronous XPC waits the isolation work found. Labels are the ones in the target's own LaunchDaemons.
static const char lite_jobs[]=
 "com.apple.identityservicesd,com.apple.locationd,com.apple.CommCenter,com.apple.bluetoothd,"
 "com.apple.photoanalysisd,com.apple.mediaanalysisd,com.apple.mediastream.mstreamd,com.apple.icloud.searchpartyd,"
 "com.apple.findmy.findmybeaconingd,com.apple.familycircled,com.apple.financed,com.apple.softwareupdateservicesd,"
 "com.apple.ndoagent,com.apple.biomesyncd,com.apple.email.maild,com.apple.amsengagementd,com.apple.adid,com.apple.eyereliefd,"
 // Crash or respawn loops seen on hardware (int-176): fairplayd.A2 is KeepAlive and exits at once (22 launches in 6 minutes), passd crashes,
 // obliteration is a data-wipe daemon with nothing to do here. iconservicesagent also dies in CI::GLContext::init, but disabling it leaves
 // the icons missing (seen on hardware), so it stays enabled. coreduetd keeps one thread above 50 % of a core for the whole boot
 // (the kernel's "burning CPU" report in i480 to i556), holding a big core and the P domain at its top clock.
 "com.apple.fairplayd.A2,com.apple.passd,com.apple.mobile.obliteration,com.apple.coreduetd,"
 // Advice and statistics services with nothing to advise on here (untagged-3f2bd680: PerfPowerServices alone held 1.8 of 7 CPUs while it
 // wrote its power database, BackgroundShortcutRunner 0.3 to 0.5 all boot, duetexpertd 0.17 in Safari). Temporarily disabled to measure.
 "com.apple.PerfPowerServices,com.apple.PerfPowerServicesExtended,com.apple.perfpowermetricd,com.apple.siriinferenced,"
 "com.apple.siriknowledged,com.apple.siriactionsd,com.apple.duetexpertd,com.apple.modelcatalogd";
static char policy[2048],jobs[200];
volatile int sheng_watchdog_policy_status=-1;

// sheng-setup=1 or sheng-data-reset=2 (the install entry's "show Hello" choice): remove Setup's completion flags once, so this boot shows the Hello page.
// iPadOS writes them again when Setup finishes, so later boots do not show it. Absent files are fine.
static int sheng_boot_setup_reset(proc_t p,uint64_t scratch) {
 static const char *const files[]={
  "/private/var/mobile/Library/Preferences/com.apple.purplebuddy.plist",
  "/private/var/mobile/Library/Preferences/com.apple.purplebuddy.notbackedup.plist"};
 for(unsigned i=0;i<sizeof(files)/sizeof(files[0]);++i) {
  int32_t result=0;
  int error=copyout(files[i],scratch,strlen(files[i])+1);
  if(error)return error;
  struct unlink_args rm={.path=scratch};
  error=unlink(p,&rm,&result);
  if(error && error!=ENOENT)return error;
 }
 return 0;
}

// The official 21H461 skip-setup profile (OddlyLabs/UniXNU scripts/seed-data-skip-setup.py, whose
// values trace to dipa-studio/ios-sweet's hardware-established set), as whole XML plists. The seed
// tool merges these keys into existing files on a seed it can mount; this writer replaces the files,
// which is safe only under the SetupDone gate in sheng_boot_skip_setup: it writes while the files are
// still first-run files and never touches them again once Setup reads as done. The springboard file
// also carries the tool's --no-auto-dim keys: without them SpringBoard dims and sleeps about 30 s
// after it starts on a board with no buttons, and the boot looks dead.
static const char pref_purplebuddy[]=
 "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
 "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
 "<plist version=\"1.0\">\n"
 "<dict>\n"
 "\t<key>SetupDone</key>\n"
 "\t<true/>\n"
 "\t<key>SetupFinishedAllSteps</key>\n"
 "\t<true/>\n"
 "\t<key>SetupVersion</key>\n"
 "\t<integer>11</integer>\n"
 "\t<key>daemonizeNeedsToRun</key>\n"
 "\t<false/>\n"
 "</dict>\n"
 "</plist>\n";
static const char pref_purplebuddy_nb[]=
 "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
 "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
 "<plist version=\"1.0\">\n"
 "<dict>\n"
 "\t<key>ShouldRunDiagnosticsMiniBuddy</key>\n"
 "\t<false/>\n"
 "\t<key>ShouldRunHSA2MiniBuddy</key>\n"
 "\t<false/>\n"
 "\t<key>ShouldRunKeychainSyncMiniBuddy</key>\n"
 "\t<false/>\n"
 "\t<key>ShouldRunMesaMiniBuddy</key>\n"
 "\t<false/>\n"
 "\t<key>ShouldRunPaymentMiniBuddy</key>\n"
 "\t<false/>\n"
 "\t<key>ShouldRunStandardMiniBuddy</key>\n"
 "\t<false/>\n"
 "\t<key>SilentICDPUpgrade</key>\n"
 "\t<false/>\n"
 "</dict>\n"
 "</plist>\n";
static const char pref_mc_nb[]=
 "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
 "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
 "<plist version=\"1.0\">\n"
 "<dict>\n"
 "\t<key>LockdownActivationIndicatesCloudConfigurationAvailable</key>\n"
 "\t<false/>\n"
 "</dict>\n"
 "</plist>\n";
static const char pref_migration[]=
 "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
 "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
 "<plist version=\"1.0\">\n"
 "<dict>\n"
 "\t<key>DMUserDataDisposition</key>\n"
 "\t<dict>\n"
 "\t\t<key>SyntheticDidUpgrade</key>\n"
 "\t\t<false/>\n"
 "\t\t<key>buildVersion</key>\n"
 "\t\t<string>21H461</string>\n"
 "\t</dict>\n"
 "\t<key>LastSystemVersion</key>\n"
 "\t<string>21H461</string>\n"
 "</dict>\n"
 "</plist>\n";
static const char pref_springboard[]=
 "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
 "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
 "<plist version=\"1.0\">\n"
 "<dict>\n"
 "\t<key>BKNoWatchdogs</key>\n"
 "\t<true/>\n"
 "\t<key>FBLaunchWatchdogExceptions</key>\n"
 "\t<dict>\n"
 "\t\t<key>com.apple.purplebuddy</key>\n"
 "\t\t<real>100.0</real>\n"
 "\t</dict>\n"
 "\t<key>MCForceShowCloudConfigurationUI</key>\n"
 "\t<false/>\n"
 "\t<key>SBDisableAutoDim</key>\n"
 "\t<true/>\n"
 "\t<key>SBDisableIdleSleep</key>\n"
 "\t<true/>\n"
 "\t<key>SBDontDimOrLockOnAC</key>\n"
 "\t<true/>\n"
 "</dict>\n"
 "</plist>\n";
static const struct {const char *name;const char *text;} skip_setup_prefs[]={
 {"com.apple.purplebuddy.plist",pref_purplebuddy},
 {"com.apple.purplebuddy.notbackedup.plist",pref_purplebuddy_nb},
 {"com.apple.managedconfiguration.notbackedup.plist",pref_mc_nb},
 {"com.apple.migration.plist",pref_migration},
 {"com.apple.springboard.plist",pref_springboard}};

// mkdir every level of an absolute directory path; EEXIST is fine. Same scratch discipline as the
// writes below: the path goes at +0.
static int policy_mkdir_chain(proc_t p,uint64_t scratch,const char *path) {
 char buf[256];size_t n=strlen(path);if(n>=sizeof(buf))return ENAMETOOLONG;memcpy(buf,path,n+1);
 for(size_t i=1;i<=n;++i) {
  if(buf[i]!='/' && buf[i]!=0)continue;
  char save=buf[i];buf[i]=0;
  int error=copyout(buf,scratch,strlen(buf)+1);
  if(!error) {struct mkdir_args md={.path=scratch,.mode=0755};int32_t result=0;error=mkdir(p,&md,&result);if(error==EEXIST)error=0;}
  buf[i]=save;
  if(error)return error;
 }
 return 0;
}

// Write one file with the disabled.plist write's discipline: path at +0, content out in 0x1f0 pieces
// through +0x200 (the cache-mount environment slots live at +0x400), stat buffer at +0x800, and the
// same close-out verification (owner, mode, regular file, exact size).
static int policy_write_file(proc_t p,uint64_t scratch,const char *path,const char *text,uid_t uid,gid_t gid,unsigned mode) {
 int error=0,fd=-1;int32_t result=0;
 if((error=copyout(path,scratch,strlen(path)+1)))goto done;
 struct open_args op={.path=scratch,.flags=O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW,.mode=mode};
 if((error=open(p,&op,&result)))goto done;
 fd=result;
 for(size_t sent=0,total=strlen(text);sent<total;) {
  size_t piece=total-sent<0x1f0?total-sent:0x1f0;
  if((error=copyout(text+sent,scratch+0x200,piece)))goto done;
  struct write_args wr={.fd=fd,.cbuf=scratch+0x200,.nbyte=piece};
  user_ssize_t written=0;
  if((error=write(p,&wr,&written)))goto done;
  if(written!=(user_ssize_t)piece){error=EIO;goto done;}
  sent+=piece;
 }
 struct fchown_args owner={.fd=fd,.uid=uid,.gid=gid};
 if((error=fchown(p,&owner,&result)))goto done;
 struct fchmod_args fm={.fd=fd,.mode=mode};
 if((error=fchmod(p,&fm,&result)))goto done;
 struct fsync_args sync={.fd=fd};
 if((error=fsync(p,&sync,&result)))goto done;
 struct fstat64_args sa={.fd=fd,.ub=scratch+0x800};struct stat64 st={0};
 if((error=sys_fstat64(p,&sa,&result)) || (error=copyin(sa.ub,&st,sizeof(st))))goto done;
 if(st.st_uid!=uid || st.st_gid!=gid || !S_ISREG(st.st_mode) || (st.st_mode&0777)!=mode || st.st_size!=(off_t)(strlen(text)))error=EINVAL;
 done:
 if(fd>=0){struct close_args cl={.fd=fd};int e=sys_close(p,&cl,&result);if(!error)error=e;}
 return error;
}

static char probe_buf[8192];
// 1 when the existing purplebuddy plist already records Setup as done, 0 when it does not, -1 when it
// cannot be read. The byte string "SetupDone" appears in both the XML and the binary plist encodings,
// so a raw scan settles it without a plist parser. Only the first 8 KiB are scanned: a first-run
// purplebuddy plist is a few hundred bytes, and a miss on a larger file falls back to writing, which
// is the pre-gate behaviour.
static int policy_setup_done(proc_t p,uint64_t scratch) {
 const char *path="/private/var/mobile/Library/Preferences/com.apple.purplebuddy.plist";
 int32_t result=0;int fd=-1;
 if(copyout(path,scratch,strlen(path)+1))return -1;
 struct open_args op={.path=scratch,.flags=O_RDONLY|O_NOFOLLOW};
 if(open(p,&op,&result))return -1;
 fd=result;
 size_t got=0;
 while(got<sizeof(probe_buf)) {
  size_t want=sizeof(probe_buf)-got<0x1f0?sizeof(probe_buf)-got:0x1f0;
  struct read_args rd={.fd=fd,.cbuf=scratch+0x200,.nbyte=want};
  user_ssize_t n=0;
  if(read(p,&rd,&n) || n<=0)break;
  if(copyin(scratch+0x200,probe_buf+got,(size_t)n))break;
  got+=(size_t)n;
  if((size_t)n<want)break;
 }
 {struct close_args cl={.fd=fd};sys_close(p,&cl,&result);}
 if(!got)return -1;
 const char needle[]="SetupDone";
 for(size_t i=0;i+sizeof(needle)-1<=got;++i)if(!memcmp(probe_buf+i,needle,sizeof(needle)-1))return 1;
 return 0;
}

// The writer's outcome, exported for FuxiBootProgress.c, which appends it to the photographed
// panic string next to the persist counters: the writer's own printf lines live only in the
// console stream and never reach that page, so chain58's photograph could not prove the writer
// ran. result is -1 until the writer runs, then its first collected error (0 = the profile is
// in place); probe is -2 until it runs, then policy_setup_done's value (-1 unreadable, 0 Setup
// was not done and the writer wrote, 1 Setup already done and nothing was written).
volatile int sheng_skip_setup_result=-1;
volatile int sheng_skip_setup_probe=-2;

// sheng-skip-setup=1: write the skip-setup profile into the mounted (persistent) Data volume. The
// caller ignores this function's return value on purpose: the policy's own return value panics
// load_init_program, and a preference write must never be able to stop a boot. The worst outcome of
// any failure here is that the Setup pages appear.
static int sheng_boot_skip_setup(proc_t p,uint64_t scratch) {
 const char *dir="/private/var/mobile/Library/Preferences";
 int probe=policy_setup_done(p,scratch);
 sheng_skip_setup_probe=probe;
 if(probe==1){sheng_skip_setup_result=0;printf("sheng skip-setup: Setup already done, preferences left alone\n");return 0;}
 int first=0,error=policy_mkdir_chain(p,scratch,dir);if(error)first=error;
 for(unsigned i=0;i<sizeof(skip_setup_prefs)/sizeof(skip_setup_prefs[0]);++i) {
  char path[256];
  strlcpy(path,dir,sizeof(path));strlcat(path,"/",sizeof(path));strlcat(path,skip_setup_prefs[i].name,sizeof(path));
  error=policy_write_file(p,scratch,path,skip_setup_prefs[i].text,501,501,0600);
  if(error && !first)first=error;
 }
 // The container directories the seed tool creates alongside the preferences; on this Data volume
 // the system has long since made them, so these are belt and braces for a younger volume.
 static const char *const containers[]={"/private/var/containers/Bundle","/private/var/containers/Data/System","/private/var/containers/Shared/SystemGroup","/private/var/containers/Temp"};
 for(unsigned i=0;i<sizeof(containers)/sizeof(containers[0]);++i){error=policy_mkdir_chain(p,scratch,containers[i]);if(error && !first)first=error;}
 printf("sheng skip-setup preferences: %d (probe %d)\n",first,probe);
 sheng_skip_setup_result=first;
 return first;
}

// One comma-separated label at *c into the policy as a disabled key; advances *c past it.
static int append_job(const char **cursor) {
 const char *c=*cursor,*e=c;while(*e && *e!=',')++e;
 if(e>c) {
  if(strlcat(policy,"<key>",sizeof(policy))>=sizeof(policy))return EINVAL;
  size_t at=strlen(policy);if(at+(size_t)(e-c)+1>=sizeof(policy))return EINVAL;
  memcpy(policy+at,c,(size_t)(e-c));policy[at+(size_t)(e-c)]=0;
  if(strlcat(policy,"</key><true/>",sizeof(policy))>=sizeof(policy))return EINVAL;
 }
 *cursor=*e?e+1:e;return 0;
}

int sheng_boot_watchdog_policy(void *process, uint64_t scratch) {
 proc_t p=process;
 int enabled=0,error=0,fd=-1;int32_t result=0;
 PE_parse_boot_argn("sheng-disable-watchdogd",&enabled,sizeof(enabled));
 if(!PE_parse_boot_argn("sheng-disable-jobs",jobs,sizeof(jobs)))jobs[0]=0;jobs[sizeof(jobs)-1]=0;
 int lite=0;PE_parse_boot_argn("sheng-lite",&lite,sizeof(lite));if(lite!=1)lite=0;
 if(enabled!=1)enabled=0;
 for(const char *c=jobs;*c;++c)if(!((*c>='a'&&*c<='z')||(*c>='A'&&*c<='Z')||(*c>='0'&&*c<='9')||*c=='.'||*c=='-'||*c==','))return EINVAL;
 int setup=0,reset=0;
 PE_parse_boot_argn("sheng-setup",&setup,sizeof(setup));
 PE_parse_boot_argn("sheng-data-reset",&reset,sizeof(reset));   // 2 = erase Data and show the Hello page; 1 = erase Data, Setup stays skipped
 if(reset==2)setup=1;
 int skip_setup=0;
 PE_parse_boot_argn("sheng-skip-setup",&skip_setup,sizeof(skip_setup));
 if(skip_setup!=1)skip_setup=0;
 if(setup==1 && (error=sheng_boot_setup_reset(p,scratch))) {
  sheng_watchdog_policy_status=error;
  printf("sheng setup flags reset failed: %d\n",error);
  return error;
 }
 if(setup==1)printf("sheng setup flags reset: Hello page on this boot\n");
 // The skip-setup writer's result is deliberately not propagated: this function's return value
 // panics load_init_program, and marking Setup done must never be able to stop a boot. Do not set
 // sheng-setup and sheng-skip-setup together; the reset above deletes the purplebuddy files first
 // and the writer would then recreate them, so the boot would skip Setup after all.
 if(skip_setup==1)sheng_boot_skip_setup(p,scratch);
 if(!enabled && !jobs[0] && !lite)return 0;
 policy[0]=0;strlcat(policy,policy_head,sizeof(policy));
 if(enabled)strlcat(policy,policy_watchdogd,sizeof(policy));
 if(lite)for(const char *c=lite_jobs;*c;) {if((error=append_job(&c)))return error;}
 for(const char *c=jobs;*c;) {if((error=append_job(&c)))return error;}
 strlcat(policy,policy_tail,sizeof(policy));
 const char *directory="/private/var/db/com.apple.xpc.launchd";
 const char *path="/private/var/db/com.apple.xpc.launchd/disabled.plist";
 if((error=copyout(directory,scratch,strlen(directory)+1)))goto done;
 struct mkdir_args md={.path=scratch,.mode=0755};
 error=mkdir(p,&md,&result);
 if(error && error!=EEXIST)goto done;
 if((error=copyout(path,scratch,strlen(path)+1)))goto done;
 // With persistent Data the previous boot's file is there: this policy is rewritten in place on every boot (it must follow the
 // boot arguments). Symlinks are still refused (O_NOFOLLOW) and the fstat check below insists on a root-owned regular file.
 struct open_args op={.path=scratch,.flags=O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW,.mode=0644};
 if((error=open(p,&op,&result)))goto done;
 fd=result;
 // The scratch page keeps the cache-mount environment slots at +0x400, so the policy (the lite list makes it longer than 0x200 bytes) goes
 // out in pieces through the 0x200 bytes at +0x200.
 for(size_t sent=0,total=strlen(policy);sent<total;) {
  size_t piece=total-sent<0x1f0?total-sent:0x1f0;
  if((error=copyout(policy+sent,scratch+0x200,piece)))goto done;
  struct write_args wr={.fd=fd,.cbuf=scratch+0x200,.nbyte=piece};
  user_ssize_t written=0;
  if((error=write(p,&wr,&written)))goto done;
  if(written!=(user_ssize_t)piece){error=EIO;goto done;}
  sent+=piece;
 }
 struct fchown_args owner={.fd=fd,.uid=0,.gid=0};
 if((error=fchown(p,&owner,&result)))goto done;
 struct fchmod_args mode={.fd=fd,.mode=0644};
 if((error=fchmod(p,&mode,&result)))goto done;
 struct fsync_args sync={.fd=fd};
 if((error=fsync(p,&sync,&result)))goto done;
 // Preserve the cache-mount environment slots at +0x400, +0x500, +0x600.
 struct fstat64_args sa={.fd=fd,.ub=scratch+0x800};struct stat64 st={0};
 if((error=sys_fstat64(p,&sa,&result)) || (error=copyin(sa.ub,&st,sizeof(st))))goto done;
 if(st.st_uid!=0 || st.st_gid!=0 || !S_ISREG(st.st_mode) || (st.st_mode&0777)!=0644 || st.st_size!=(off_t)(strlen(policy)))error=EINVAL;
 done:
 if(fd>=0){struct close_args cl={.fd=fd};int e=sys_close(p,&cl,&result);if(!error)error=e;}
 // A real empty migration marker selects the qualified modern override loader.
 if(!error) {
  const char *marker="/private/var/db/com.apple.xpc.launchd/disabled.migrated";
  error=copyout(marker,scratch,strlen(marker)+1);
  if(!error) {
   struct open_args mark={.path=scratch,.flags=O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,.mode=0644};
   error=open(p,&mark,&result);
   if(!error){struct close_args cl={.fd=result};error=sys_close(p,&cl,&result);}
   else if(error==EEXIST)error=0;
  }
 }
 sheng_watchdog_policy_status=error;
 printf("sheng bring-up watchdogd launch policy: %d (hardware watchdog not implemented)\n",error);
 return error;
}
