### NOTES ###

# These example lines should be executed from the main directory

# cp is the lagrange multiplier in front of the main data term.
# Usually cp is 1: this doesn't change anything in theory (we're optimizing a linear program), but in practice it
# can affect the approximations made in MOSEK.

# ca is a lagrange multiplier associated to a term that penalizes the total area of the reconstruction.
# it is usually not used when dealing with lines (it is set to 0 in all our examples), but it is left in the program.
# Feel free to experiment with it.

#############

# Andalusian

mkdir -p result/demo-Andalusian
build/line_based_recons -i data/Andalusian/input_lines_from_residuals.json -o result/demo-Andalusian/ -cp 1 -cv 1 -ca 0 -ce 0.1 -cc 0.1 -ext -v

# Barn

# The line output from Line3d++ is very noisy for this example. Therefore it requires a strong regularization.

mkdir -p result/demo-Barn
build/line_based_recons -i data/Barn/input_lines_from_residuals.json -o result/demo-Barn/ -cp 10 -cv 5 -ca 0 -ce 10 -cc 10 -ext -v

# Bridge

mkdir -p result/demo-Bridge
build/line_based_recons -i data/Bridge/input_lines_from_residuals.json -o result/demo-Bridge/ -cp 1 -cv 1 -ca 0 -ce 0.1 -cc 0.1 -int -v

# HouseInterior

mkdir -p result/demo-HouseInterior
build/line_based_recons -i data/HouseInterior/input_lines_from_residuals.json -o result/demo-HouseInterior/ -cp 10 -cv 1 -ca 0 -ce 0.01 -cc 0.1 -int -v

# TimberFrame

mkdir -p result/demo-TimberFrame
build/line_based_recons -i data/TimberFrame/input_lines_from_residuals.json -o result/demo-TimberFrame/ -cp 1 -cv 1 -ca 0 -ce 1 -cc 1 -ext -v
