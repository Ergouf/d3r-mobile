#include <stop_token>
#include <thread>
int main(){ std::stop_source s; std::jthread t; (void)s; return 0; }
