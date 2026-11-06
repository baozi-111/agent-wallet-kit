// Pearl GPU miner multi-find
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <string>
#include <fstream>
#include <sstream>
#include <chrono>
#include <ctime>
#include <sys/stat.h>
#include <sys/types.h>
#ifdef _WIN32
#include <direct.h>
#endif
#include <vector>
#include <cuda_runtime.h>

#define CHECK(call) do{ cudaError_t e=(call); if(e!=cudaSuccess){ \
  fprintf(stderr,"CUDA %s:%d %s\n",__FILE__,__LINE__,cudaGetErrorString(e)); exit(1);} }while(0)

__device__ __forceinline__ uint64_t rotl64(uint64_t x, int n){ return (x<<n)|(x>>(64-n)); }

__device__ void keccak_f1600(uint64_t st[25]){
  static const uint64_t RC[24]={
    0x0000000000000001ULL,0x0000000000008082ULL,0x800000000000808aULL,0x8000000080008000ULL,
    0x000000000000808bULL,0x0000000080000001ULL,0x8000000080008081ULL,0x8000000000008009ULL,
    0x000000000000008aULL,0x0000000000000088ULL,0x0000000080008009ULL,0x000000008000000aULL,
    0x000000008000808bULL,0x800000000000008bULL,0x8000000000008089ULL,0x8000000000008003ULL,
    0x8000000000008002ULL,0x8000000000000080ULL,0x000000000000800aULL,0x800000008000000aULL,
    0x8000000080008081ULL,0x8000000000008080ULL,0x0000000080000001ULL,0x8000000080008008ULL};
  static const int rotc[24]={1,3,6,10,15,21,28,36,45,55,2,14,27,41,56,8,25,43,62,18,39,61,20,44};
  static const int piln[24]={10,7,11,17,18,3,5,16,8,21,24,4,15,23,19,13,12,2,20,14,22,9,6,1};
  for(int round=0;round<24;round++){
    uint64_t bc[5];
    for(int i=0;i<5;i++) bc[i]=st[i]^st[i+5]^st[i+10]^st[i+15]^st[i+20];
    for(int i=0;i<5;i++){
      uint64_t t=bc[(i+4)%5]^rotl64(bc[(i+1)%5],1);
      for(int j=0;j<25;j+=5) st[j+i]^=t;
    }
    uint64_t t=st[1];
    for(int i=0;i<24;i++){
      int j=piln[i];
      bc[0]=st[j];
      st[j]=rotl64(t,rotc[i]);
      t=bc[0];
    }
    for(int j=0;j<25;j+=5){
      uint64_t a0=st[j],a1=st[j+1],a2=st[j+2],a3=st[j+3],a4=st[j+4];
      st[j]  =a0 ^ ((~a1)&a2);
      st[j+1]=a1 ^ ((~a2)&a3);
      st[j+2]=a2 ^ ((~a3)&a4);
      st[j+3]=a3 ^ ((~a4)&a0);
      st[j+4]=a4 ^ ((~a0)&a1);
    }
    st[0]^=RC[round];
  }
}

__device__ bool hash_ok(const uint8_t seed[32], uint64_t nonce_lo, const uint8_t target_be[32]){
  uint64_t st[25];
  #pragma unroll
  for(int i=0;i<25;i++) st[i]=0;
  uint8_t msg[136];
  #pragma unroll
  for(int i=0;i<32;i++) msg[i]=seed[i];
  #pragma unroll
  for(int i=0;i<24;i++) msg[32+i]=0;
  msg[56]=(uint8_t)(nonce_lo>>56); msg[57]=(uint8_t)(nonce_lo>>48);
  msg[58]=(uint8_t)(nonce_lo>>40); msg[59]=(uint8_t)(nonce_lo>>32);
  msg[60]=(uint8_t)(nonce_lo>>24); msg[61]=(uint8_t)(nonce_lo>>16);
  msg[62]=(uint8_t)(nonce_lo>>8);  msg[63]=(uint8_t)(nonce_lo);
  #pragma unroll
  for(int i=64;i<136;i++) msg[i]=0;
  msg[64]=0x01;
  msg[135]|=0x80;
  for(int i=0;i<17;i++){
    uint64_t lane=0;
    #pragma unroll
    for(int b=0;b<8;b++) lane|=((uint64_t)msg[i*8+b])<<(8*b);
    st[i]^=lane;
  }
  keccak_f1600(st);
  uint8_t h[32];
  for(int i=0;i<4;i++){
    uint64_t lane=st[i];
    #pragma unroll
    for(int b=0;b<8;b++) h[i*8+b]=(uint8_t)(lane>>(8*b));
  }
  for(int i=0;i<32;i++){
    if(h[i]<target_be[i]) return true;
    if(h[i]>target_be[i]) return false;
  }
  return true;
}

__device__ volatile int g_found;
__device__ unsigned long long g_nonce;
__device__ unsigned long long g_hashes;

__global__ void mine_kernel(const uint8_t* seed, const uint8_t* target_be, unsigned long long start, unsigned long long count){
  unsigned long long idx = start + (unsigned long long)blockIdx.x * blockDim.x + threadIdx.x;
  unsigned long long stride = (unsigned long long)gridDim.x * blockDim.x;
  unsigned long long end = start + count;
  unsigned long long local=0;
  for(unsigned long long n=idx; n<end; n+=stride){
    if(g_found) break;
    local++;
    if(hash_ok(seed, n, target_be)){
      if(atomicCAS((int*)&g_found, 0, 1)==0){
        g_nonce=n;
      }
      break;
    }
  }
  atomicAdd(&g_hashes, local);
}

static bool parse_hex32(const std::string& s, uint8_t out[32]){
  std::string h=s; if(h.rfind("0x",0)==0||h.rfind("0X",0)==0) h=h.substr(2);
  if(h.size()!=64) return false;
  for(int i=0;i<32;i++){
    unsigned v; if(sscanf(h.c_str()+i*2,"%2x",&v)!=1) return false; out[i]=(uint8_t)v;
  }
  return true;
}

static void u256_to_be32(const std::string& dec, uint8_t out[32]){
  uint8_t a[32]={0};
  for(char c: dec){
    if(c<'0'||c>'9') continue;
    int carry=c-'0';
    for(int i=31;i>=0;i--){ int v=a[i]*10+carry; a[i]=(uint8_t)(v&0xff); carry=v>>8; }
  }
  memcpy(out,a,32);
}

static std::string json_get(const std::string& j, const std::string& key){
  auto k="\""+key+"\""; auto p=j.find(k); if(p==std::string::npos) return "";
  p=j.find(':',p); if(p==std::string::npos) return "";
  p=j.find_first_not_of(" \t\n\r", p+1);
  if(p==std::string::npos) return "";
  if(j[p]=='"'){ auto q=j.find('"',p+1); return j.substr(p+1,q-p-1); }
  auto q=j.find_first_of(",}\n\r",p); return j.substr(p,q-p);
}

int main(int argc, char** argv){
  const char* path = argc>1? argv[1] : "pearl-challenge.json";
  std::ifstream in(path); if(!in){ fprintf(stderr,"cannot open %s\n",path); return 1; }
  std::stringstream buf; buf<<in.rdbuf(); std::string j=buf.str();
  std::string seed_s=json_get(j,"seed");
  std::string target_s=json_get(j,"target");
  if(seed_s.empty()||target_s.empty()){ fprintf(stderr,"bad challenge json\n"); return 1; }
  uint8_t seed[32], target_be[32];
  if(!parse_hex32(seed_s, seed)){ fprintf(stderr,"bad seed\n"); return 1; }
  u256_to_be32(target_s, target_be);

  int lim = 570; if(const char* e=getenv("PEARL_LIMIT_SEC")) lim=atoi(e);
  int want = 16; if(const char* e=getenv("PEARL_FIND_COUNT")) want=atoi(e);
  if(want<1) want=1; if(want>16) want=16;
  int threads=256, blocks=0;
  if(const char* e=getenv("PEARL_CUDA_THREADS")) threads=atoi(e);
  cudaDeviceProp prop; CHECK(cudaGetDeviceProperties(&prop,0));
  if(const char* e=getenv("PEARL_CUDA_BLOCKS")) blocks=atoi(e);
  if(blocks<=0) blocks = prop.multiProcessorCount * 8;
  printf("GPU: %s | SMs=%d | blocks=%d threads=%d | limit=%ds | want=%d\n", prop.name, prop.multiProcessorCount, blocks, threads, lim, want);
  printf("seed=%s...\n", seed_s.substr(0,18).c_str());

  uint8_t *d_seed,*d_target; CHECK(cudaMalloc(&d_seed,32)); CHECK(cudaMalloc(&d_target,32));
  CHECK(cudaMemcpy(d_seed,seed,32,cudaMemcpyHostToDevice));
  CHECK(cudaMemcpy(d_target,target_be,32,cudaMemcpyHostToDevice));

  auto t0=std::chrono::steady_clock::now();
  unsigned long long cursor=(unsigned long long)time(nullptr)*1000003ULL;
  // skip known used small nonce region a bit; also skip first found if restart
  if(const char* e=getenv("PEARL_START_NONCE")) cursor=strtoull(e,nullptr,10);
  unsigned long long skip_nonce = 0;
  if(const char* e=getenv("PEARL_SKIP_NONCE")) skip_nonce=strtoull(e,nullptr,10);
  const unsigned long long batch = (unsigned long long)blocks * threads * 4096ULL;
  std::vector<unsigned long long> founds;
  unsigned long long total_hashes=0;

  while((int)founds.size()<want){
    auto now=std::chrono::steady_clock::now();
    double sec=std::chrono::duration<double>(now-t0).count();
    if(sec>=lim) break;
    int zero=0; unsigned long long z=0;
    CHECK(cudaMemcpyToSymbol(g_found,&zero,sizeof(zero)));
    CHECK(cudaMemcpyToSymbol(g_nonce,&z,sizeof(z)));
    CHECK(cudaMemcpyToSymbol(g_hashes,&z,sizeof(z)));
    mine_kernel<<<blocks,threads>>>(d_seed,d_target,cursor,batch);
    CHECK(cudaGetLastError());
    CHECK(cudaDeviceSynchronize());
    unsigned long long hashes=0; CHECK(cudaMemcpyFromSymbol(&hashes,g_hashes,sizeof(hashes)));
    total_hashes+=hashes;
    int hf=0; CHECK(cudaMemcpyFromSymbol(&hf,g_found,sizeof(hf)));
    if(hf){
      unsigned long long n=0; CHECK(cudaMemcpyFromSymbol(&n,g_nonce,sizeof(n)));
      bool dup=false; for(auto x:founds) if(x==n) dup=true;
      if(!dup && (skip_nonce==0 || n!=skip_nonce)){
        founds.push_back(n);
        printf("FOUND #%zu nonce=%llu  (%.1fs, total_hashes=%llu)\n", founds.size(), n, sec, total_hashes);
        fflush(stdout);
      }
      cursor = n + 1;
    } else {
      cursor += batch;
    }
    now=std::chrono::steady_clock::now();
    sec=std::chrono::duration<double>(now-t0).count();
    double rate = total_hashes / (sec>0.001?sec:0.001) / 1e6;
    printf("[进度] have=%zu/%d  cursor=%llu  ~%.0f MH/s  %.0fs\n", founds.size(), want, cursor, rate, sec);
    fflush(stdout);
  }

  auto t1=std::chrono::steady_clock::now();
  double elapsed=std::chrono::duration<double>(t1-t0).count();
  double mhs = total_hashes / (elapsed>0.001?elapsed:0.001) / 1e6;
  printf("DONE have=%zu elapsed=%.2fs hashes=%llu ~%.1f MH/s\n", founds.size(), elapsed, total_hashes, mhs);

  std::string wallet_s=json_get(j,"wallet");
  std::string agent_s=json_get(j,"agent_id");
  std::string reward_s=json_get(j,"reward");
  std::string handle_s=json_get(j,"handle");
  std::string token_s=json_get(j,"token");

  auto write_solutions=[&](const std::string& path){
    std::ofstream out(path);
    out<<"{\n";
    out<<"  \"seed\": \""<<seed_s<<"\",\n";
    out<<"  \"target\": \""<<target_s<<"\",\n";
    out<<"  \"engine\": \"cuda\",\n";
    out<<"  \"elapsed\": "<<elapsed<<",\n";
    out<<"  \"mhs\": "<<mhs<<",\n";
    out<<"  \"hashes\": \""<<total_hashes<<"\",\n";
    if(!wallet_s.empty()) out<<"  \"wallet\": \""<<wallet_s<<"\",\n";
    if(!agent_s.empty()) out<<"  \"agent_id\": \""<<agent_s<<"\",\n";
    if(!handle_s.empty()) out<<"  \"handle\": \""<<handle_s<<"\",\n";
    if(!token_s.empty()) out<<"  \"token\": \""<<token_s<<"\",\n";
    if(!reward_s.empty()) out<<"  \"reward\": \""<<reward_s<<"\",\n";
    out<<"  \"nonces\": [";
    for(size_t i=0;i<founds.size();i++){ if(i) out<<", "; out<<"\""<<founds[i]<<"\""; }
    out<<"]\n}\n";
  };

  write_solutions("pearl-solutions.json");
  // also mirror to PEARL_OUTBOX / outbox if set or present
  const char* outbox_env = getenv("PEARL_OUTBOX");
  std::string outbox = outbox_env ? outbox_env : "outbox";
  // create outbox best-effort (Windows: mkdir via system; ignore errors)
#ifdef _WIN32
  _mkdir(outbox.c_str());
#else
  mkdir(outbox.c_str(), 0755);
#endif
  {
    auto now_t = std::chrono::system_clock::now();
    std::time_t tt = std::chrono::system_clock::to_time_t(now_t);
    std::tm tm{};
#ifdef _WIN32
    localtime_s(&tm, &tt);
#else
    localtime_r(&tt, &tm);
#endif
    char tsbuf[32];
    std::strftime(tsbuf, sizeof(tsbuf), "%Y%m%d-%H%M%S", &tm);
    std::string stamped = outbox + "/pearl-batch-" + tsbuf + ".json";
    write_solutions(stamped);
    write_solutions("pearl-solutions-latest.json");
    printf("WROTE pearl-solutions.json + %s + pearl-solutions-latest.json (%zu) ~%.1f MH/s\n",
           stamped.c_str(), founds.size(), mhs);
  }
  if(!founds.empty()){
    std::ofstream out1("pearl-solution.json");
    out1<<"{\n  \"nonce\": \""<<founds[0]<<"\",\n  \"elapsed\": "<<elapsed<<",\n  \"mhs\": "<<mhs<<",\n  \"seed\": \""<<seed_s<<"\",\n  \"target\": \""<<target_s<<"\",\n  \"engine\": \"cuda\"\n}\n";
  }
  cudaFree(d_seed); cudaFree(d_target);
  return founds.empty()?2:0;
}
