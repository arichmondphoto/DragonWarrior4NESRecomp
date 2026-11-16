# Cross-compiling for 64-bit Windows with MinGW-w64 (windows/build_in_env.sh).
# The "-posix" compilers are the thread model C++'s std::thread needs; distros
# without the suffix (Arch/Manjaro's mingw-w64-gcc) are already posix.
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86_64)
set(_mingw x86_64-w64-mingw32)

find_program(_mingw_cc NAMES ${_mingw}-gcc-posix ${_mingw}-gcc REQUIRED)
find_program(_mingw_cxx NAMES ${_mingw}-g++-posix ${_mingw}-g++ REQUIRED)
set(CMAKE_C_COMPILER "${_mingw_cc}")
set(CMAKE_CXX_COMPILER "${_mingw_cxx}")
set(CMAKE_RC_COMPILER ${_mingw}-windres)

set(CMAKE_FIND_ROOT_PATH /usr/${_mingw} /usr/lib/gcc/${_mingw})
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
# SDL2 lives outside the root path (SDL2_DIR points at it).
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE BOTH)

# The generated game code makes very large object files (MSVC's /bigobj).
set(CMAKE_C_FLAGS_INIT "-Wa,-mbig-obj")
set(CMAKE_CXX_FLAGS_INIT "-Wa,-mbig-obj")
# The compiler's own runtime goes inside the .exe (fewer DLLs to carry);
# -mwindows: a window program, no console window behind the game.
set(CMAKE_EXE_LINKER_FLAGS_INIT "-static-libgcc -static-libstdc++ -mwindows")
