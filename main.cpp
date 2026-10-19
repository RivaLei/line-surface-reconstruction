#include "OptionParser/option_parser.h"
#include "jsonInput.h"
#include "WeightComputation.h"
#include "ArrangementToMosek.h"
#include <fstream>
#include <sys/stat.h>
#include <cerrno>
#include <cstdint>
#include "Checkpoint.h"

using namespace std;

int runMain(int argc, char* argv[])
{
    //Create parsing options
    op::OptionParser opt;
    opt.add_option("-h", "--help", "show option help");
    opt.add_option("-v", "--verbose", "Verbosity trigger");
    opt.add_option("-i", "--input", "Input line file", "");
    opt.add_option("-o", "--output", "Output directory", "./");
    opt.add_option("-cp", "--cost_primitive", "Cost for primitive terms", "1");
    opt.add_option("-cv", "--cost_visibility", "Cost for visibility term", "0.1");
    opt.add_option("-ca", "--cost_area", "Cost for facet area term", "0");
    opt.add_option("-ce", "--cost_edge", "Cost for edge term", "0.01");
    opt.add_option("-cc", "--cost_corner", "Cost for corner term", "0.01");
    opt.add_option("-vs", "--voxel-size", "Voxel size", "0");
    opt.add_option("-ext", "--exterior", "Exterior scene mode (-ext or -int REQUIRED)");
    opt.add_option("-int", "--interior", "Interior scene mode (-ext or -int REQUIRED)");
    opt.add_option("-np", "--max_number_planes", "(Optional) Max number of planes to insert", "-1");
    opt.add_option("-sa", "--save-arrangement", "Save intermediate plane arrangement to output directory/arrangement.ply before computing weights");

    opt.add_option("-nc", "--no-checkpoints", "Disable automatic checkpoint saving/loading");
    opt.add_option("-cb", "--checkpoint-batch", "Save weights after this many input lines", "100");

    //Parsing options
    bool correctParsing = opt.parse_options(argc, argv);
    if(!correctParsing)
        return EXIT_FAILURE;

    if(op::str2bool(opt["-h"]))
    {
        opt.show_help();
        return 0;
    }

    if(opt["-i"].empty())
    {
        cerr << "Input json lines file (-i) is required!" << endl;
        opt.show_help();
        return EXIT_FAILURE;
    }

    bool force_interior = op::str2bool(opt["-int"]);
    bool force_exterior = op::str2bool(opt["-ext"]);

    if (!force_exterior && !force_interior)
    {
        cerr << "Scene type should be specified ! (--exterior or --interior)" << endl;
        return EXIT_FAILURE;
    }

    if(force_exterior && force_interior)
    {
        cerr << "A scene can't be simultaneously interior and exterior !" << endl;
        return EXIT_FAILURE;
    }

    // Retrieving output path
    string outputPath = opt["-o"];
    if(outputPath[outputPath.size() - 1] != '/')
        outputPath.push_back('/');

    // Converting the parameters
    bool   verbose         = op::str2bool(opt["-v"]);
    double cost_primitive  = op::str2double(opt["-cp"]); // Reference weight
    double cost_visibility = op::str2double(opt["-cv"]);
    double cost_area       = op::str2double(opt["-ca"]);
    double cost_edge       = op::str2double(opt["-ce"]);
    double cost_corners    = op::str2double(opt["-cc"]);
    double voxel_size      = op::str2double(opt["-vs"]);
    int    maxNumberPlanes = op::str2int(opt["-np"]);

    int checkpointBatch = op::str2int(opt["-cb"]);
    if (checkpointBatch <= 0) throw runtime_error("Checkpoint batch must be positive");
    string checkpointDirectory;
    unique_ptr<checkpoint::DirectoryLock> checkpointLock;
    if (!op::str2bool(opt["-nc"])) {
        // Cache identity binds input bytes, all geometry/optimization parameters,
        // and the actual executable. Changed inputs/builds cannot reuse stale handles.
        auto hashFile = [](const string& path) {
            ifstream stream(path, ios::binary);
            if (!stream) throw runtime_error("Cannot fingerprint " + path);
            uint64_t hash = 14695981039346656037ULL;
            char buffer[65536];
            while (stream.read(buffer, sizeof(buffer)) || stream.gcount())
                for (streamsize i = 0; i < stream.gcount(); ++i) { hash ^= static_cast<unsigned char>(buffer[i]); hash *= 1099511628211ULL; }
            if (!stream.eof()) throw runtime_error("Cannot fingerprint " + path);
            return hash;
        };
        checkpoint::Json identity;
        identity["format"] = 1;
        identity["input_hash"] = hashFile(opt["-i"]);
        identity["binary_hash"] = hashFile("/proc/self/exe");
        identity["parameters"] = {cost_primitive, cost_visibility, cost_area, cost_edge, cost_corners, voxel_size, double(maxNumberPlanes), double(force_interior), double(force_exterior)};
        uint64_t key = 14695981039346656037ULL;
        for (unsigned char c : identity.dump()) { key ^= c; key *= 1099511628211ULL; }
        ostringstream name; name << hex << key;
        const string root = outputPath + "checkpoints";
        auto directory = [](const string& path) {
            if (mkdir(path.c_str(), 0777) != 0 && errno != EEXIST) throw runtime_error("Cannot create checkpoint directory: " + path);
        };
        directory(root);
        checkpointDirectory = root + "/" + name.str();
        directory(checkpointDirectory);
        checkpointLock.reset(new checkpoint::DirectoryLock(checkpointDirectory + "/lock"));
        const string manifest = checkpointDirectory + "/manifest.json";
        if (checkpoint::exists(manifest) && checkpoint::read(manifest) != identity) throw runtime_error("Checkpoint identity mismatch");
        checkpoint::write(manifest, identity);
        cout << "Checkpoint directory: " << checkpointDirectory << endl;
    }

    //Load input data
    PrimitiveSet myPrimitiveSet;
    LineSet myLineSet;
    loadInputFromJson(opt["-i"], myLineSet, myPrimitiveSet, maxNumberPlanes, verbose);

    //Orientate the planes
    int nbOfReorientation = myPrimitiveSet.orientatePrimitives(myLineSet);
    if (verbose) cout << "Nb of reoriented planes : " << nbOfReorientation << endl;

    //Make the plane arrangement, fill it and save it
    double bboxIncreaseFactor = 0.1;
    PlaneArrangement myArrangement(myLineSet.getBbox(bboxIncreaseFactor), myPrimitiveSet, voxel_size, verbose, checkpointDirectory);

    // Optional diagnostic geometry: all bounded arrangement facets, before weights
    // and optimization. This is not the reconstructed surface or a restart checkpoint.
    if (op::str2bool(opt["-sa"]))
    {
        const string arrangementPath = outputPath + "arrangement.ply";
        // Check the destination before the potentially expensive mesh extraction.
        ofstream destination(arrangementPath);
        if (!destination)
        {
            cerr << "Cannot write intermediate arrangement: " << arrangementPath
                 << ". Check that the output directory exists and is writable." << endl;
            return EXIT_FAILURE;
        }
        destination.close();
        cout << "Saving intermediate plane arrangement: " << arrangementPath << endl;
        myArrangement.saveArrangementAsPly(arrangementPath);
        ifstream savedArrangement(arrangementPath, ios::binary | ios::ate);
        if (!savedArrangement || savedArrangement.tellg() <= 0)
        {
            cerr << "Failed to save intermediate plane arrangement: " << arrangementPath << endl;
            return EXIT_FAILURE;
        }
        cout << "Intermediate plane arrangement saved; starting weight computation." << endl;
    }

    //Compute the weights
    computeWeights(myArrangement, myLineSet, 1., verbose,
                   checkpointDirectory.empty() ? "" : checkpointDirectory + "/weights.json", checkpointBatch);

    //Optimization
    bool force_filled_bounding_box = force_interior;
    bool force_empty_bounding_box = force_exterior;
    pair<vector<size_t>, map<int, int>> optResults;
    const string solutionPath = checkpointDirectory.empty() ? "" : checkpointDirectory + "/solution.json";
    if (!solutionPath.empty() && checkpoint::exists(solutionPath)) {
        auto solution = checkpoint::read(solutionPath);
        optResults.first = solution.at("labels").get<vector<size_t>>();
        if (optResults.first.size() != size_t(myArrangement.number_of_cells())) throw runtime_error("Solution checkpoint geometry mismatch");
        for (const auto& entry : solution.at("cell_to_variable"))
            optResults.second[entry.at(0).get<int>()] = entry.at(1).get<int>();
        cout << "[resume] Loaded completed optimization result." << endl;
    } else {
        ArrangementToMosek mosekOptimizer(myArrangement, cost_primitive, cost_visibility,
                                        cost_area, cost_edge, cost_corners, force_filled_bounding_box,
                                        force_empty_bounding_box, verbose);
        optResults = mosekOptimizer.setAndSolve(checkpointDirectory.empty() ? "" : checkpointDirectory + "/model.json");
        if (!solutionPath.empty()) {
            checkpoint::Json solution;
            solution["labels"] = optResults.first;
            solution["cell_to_variable"] = checkpoint::Json::array();
            for (const auto& entry : optResults.second)
                solution["cell_to_variable"].push_back({entry.first, entry.second});
            checkpoint::write(solutionPath, solution);
            cout << "[checkpoint] Saved optimization result." << endl;
        }
    }

    std::ostringstream strs;
    strs << "cp_" << cost_primitive << "_cv_" << cost_visibility << "_ca_" << cost_area << "_ce_" <<
         cost_edge << "_cc_" << cost_corners;
    std::string file_title = strs.str();

    cout << "||| saving LP" << endl;
    cout << "out folder : " <<  outputPath + file_title + ".ply" << endl;
    myArrangement.savePlyFromLabel(outputPath + file_title + ".ply", optResults.second, optResults.first);


    return 0;
}

int main(int argc, char* argv[]) {
    try { return runMain(argc, argv); }
    catch (const std::exception& error) {
        cerr << "Reconstruction failed: " << error.what() << endl;
        return EXIT_FAILURE;
    }
}
